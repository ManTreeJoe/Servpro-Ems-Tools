"""EMS / Contents / Recon: three divisions on one job.

Each keeps its own Trello card and CompanyCam project, so the audit can
switch between them. On disk they are already separate folders inside the
job — live, 166 of 623 client folders carry RECON and 99 carry CONTENTS,
and some jobs (Adamucci) are recon-only — so a division's FOLDER is
derived rather than stored, and its existence is the signal that the
division has work.

The load-bearing decision is that EMS keeps the unsuffixed link types.
Every link recorded before divisions existed is an EMS link, so the old
names already mean the right thing: no migration, and no reader has to
change to keep working.
"""
import os

import pytest

from ems_db_common import (
    DIVISIONS, DIV_EMS, DIV_CONTENTS, DIV_RECON,
    division_folder, division_link_type, normalize_division,
)
import ems_db_sqlite as db


def test_ems_keeps_the_original_link_types():
    """The whole point of the scheme. If this changes, every existing
    trello_card / companycam_project row stops resolving."""
    assert division_link_type("trello_card", DIV_EMS) == "trello_card"
    assert division_link_type("companycam_project", DIV_EMS) == \
        "companycam_project"
    assert division_link_type("trello_card") == "trello_card"


def test_the_other_divisions_get_their_own_types():
    assert division_link_type("trello_card", DIV_CONTENTS) == \
        "trello_card_contents"
    assert division_link_type("trello_card", DIV_RECON) == "trello_card_recon"
    assert division_link_type("companycam_project", DIV_RECON) == \
        "companycam_project_recon"


def test_every_division_yields_a_distinct_type():
    """Two divisions sharing a type would silently overwrite each other."""
    got = [division_link_type("trello_card", d) for d in DIVISIONS]
    assert len(set(got)) == len(DIVISIONS)


@pytest.mark.parametrize("given,want", [
    ("", DIV_EMS), (None, DIV_EMS), ("ems", DIV_EMS),
    ("mitigation", DIV_EMS),
    ("contents", DIV_CONTENTS), ("Contents", DIV_CONTENTS),
    ("CONTENT", DIV_CONTENTS),
    ("recon", DIV_RECON), ("Reconstruction", DIV_RECON), ("RC", DIV_RECON),
    ("nonsense", DIV_EMS),          # unknown falls back, never raises
])
def test_division_spellings(given, want):
    assert normalize_division(given) == want


def test_the_folder_is_derived_from_the_job_folder():
    base = r"X:\IE_Public\2026 Jobs\Abbott Darlene"
    assert division_folder(base, DIV_EMS) == os.path.join(base, "EMS")
    assert division_folder(base, DIV_CONTENTS) == os.path.join(base,
                                                               "CONTENTS")
    assert division_folder(base, DIV_RECON) == os.path.join(base, "RECON")


def test_a_trailing_separator_does_not_double_up():
    got = division_folder("X:\\IE_Public\\2026 Jobs\\Abbott Darlene\\",
                          DIV_RECON)
    assert got.endswith("Abbott Darlene" + os.sep + "RECON")


def test_no_job_folder_yields_nothing_rather_than_a_bare_division():
    """Returning 'RECON' alone would be a path relative to whatever the
    caller's cwd happened to be."""
    assert division_folder("", DIV_RECON) == ""
    assert division_folder(None, DIV_RECON) == ""


# ── storage, end to end ────────────────────────────────────────────────

def test_three_cards_live_on_one_job_without_colliding(tmp_path):
    db.reset_db_path(str(tmp_path / "t.db"))
    db.upsert_job(display_name="Abbott, Darlene- Farmers")
    key = db.canon_key("Abbott, Darlene- Farmers")

    for div, card in ((DIV_EMS, "6a839f8bd0ca072308e4f906"), (DIV_CONTENTS, "6a7e179e4dc9870562e321e1"),
                      (DIV_RECON, "6a1234567890abcdef012345")):
        db.set_link(key, division_link_type("trello_card", div), card)

    for div, card in ((DIV_EMS, "6a839f8bd0ca072308e4f906"), (DIV_CONTENTS, "6a7e179e4dc9870562e321e1"),
                      (DIV_RECON, "6a1234567890abcdef012345")):
        rows = db.get_links(key, division_link_type("trello_card", div))
        assert [r["link_value"] for r in rows] == [card], div


def test_an_existing_link_still_reads_as_ems(tmp_path):
    """A job pinned before divisions existed must keep resolving through
    the plain type — this is what makes the scheme migration-free."""
    db.reset_db_path(str(tmp_path / "t.db"))
    db.upsert_job(display_name="Agape Church")
    key = db.canon_key("Agape Church")
    db.set_link(key, db.LINK_TRELLO, "oldcard")

    rows = db.get_links(key, division_link_type("trello_card", DIV_EMS))
    assert [r["link_value"] for r in rows] == ["oldcard"]
    # ...and it is NOT visible as one of the other divisions.
    assert db.get_links(key, division_link_type("trello_card",
                                                DIV_RECON)) == []


def test_a_division_link_normalizes_like_the_ems_one(tmp_path):
    """`_norm_link` switched on the exact type, so trello_card_recon
    skipped card-id extraction entirely: the EMS card stored a clean id
    from a pasted URL while Recon stored the whole URL, and reverse
    lookup then found one and missed the other."""
    db.reset_db_path(str(tmp_path / "t.db"))
    db.upsert_job(display_name="Agape Church")
    key = db.canon_key("Agape Church")
    url = "https://trello.com/c/AbCd1234/17-agape-church-recon"

    db.set_link(key, division_link_type("trello_card", DIV_RECON), url)

    rows = db.get_links(key, division_link_type("trello_card", DIV_RECON))
    assert [r["link_value"] for r in rows] == ["abcd1234"]


def test_the_base_type_round_trips():
    from ems_db_common import base_link_type, division_of_link_type
    for d in DIVISIONS:
        t = division_link_type("trello_card", d)
        assert base_link_type(t) == "trello_card"
        assert division_of_link_type(t) == d
