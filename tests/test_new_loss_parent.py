"""Filing a new loss under a parent the NAME cannot reveal.

A commercial loss arrives titled 'Bell Mountain Middle School'. Nothing in
that string says which district owns it, so no matcher can file it
correctly — and `job_folders` matches exactly on purpose, because a fuzzy
hit at creation once nested unrelated '<Name> Property Management' jobs
inside each other.

The live share is the proof. 'Val Verde Unified School' holds
'Mead Valley 7.22.26', 'Rancho Verde 7.29.26' and 'Red Maple 7.15.26' —
not one child shares a token with its parent. So the operator picks the
parent, and nothing is inferred. 'Bell Mountain Middle School
-2507388588WTR' is loose at the root today for exactly this reason.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import job_folders as jf
import new_loss_intake as nli


@pytest.fixture
def share(tmp_path, monkeypatch):
    """A stand-in share shaped like the real one."""
    yd = tmp_path / "2026 Jobs"
    yd.mkdir()
    # An umbrella whose children share no token with it — the real shape.
    (yd / "Val Verde Unified School" / "Mead Valley 7.22.26").mkdir(parents=True)
    (yd / "Val Verde Unified School" / "Rancho Verde 7.29.26").mkdir(parents=True)
    (yd / "Menifee Union School District" / "Quail Valley Elementry").mkdir(
        parents=True)
    (yd / "Mansolino Sayra").mkdir()
    monkeypatch.setattr(jf, "year_dir", lambda **kw: str(yd))
    return str(yd)


# ── the picker ───────────────────────────────────────────────────────
def test_search_finds_a_district_by_partial_name(share):
    names = [r["name"] for r in jf.search_clients("menifee school")]
    assert "Menifee Union School District" in names, (
        "tokens in any order should find it — nobody types the full name")


def test_search_with_no_query_lists_everything(share):
    assert len(jf.search_clients("")) == 3       # the two umbrellas + Mansolino


def test_umbrellas_sort_first(share):
    """A parent is usually something that has parented before."""
    rows = jf.search_clients("")
    assert rows[0]["child_count"] > 0
    assert rows[-1]["name"] == "Mansolino Sayra"


def test_search_reports_the_children(share):
    row = next(r for r in jf.search_clients("val verde"))
    assert sorted(row["children"]) == ["Mead Valley 7.22.26",
                                       "Rancho Verde 7.29.26"]


def test_search_is_a_picker_not_a_matcher(share):
    """It must never be wired into creation — that is the rule this
    module exists under. Suggesting is safe; choosing is not."""
    import inspect
    for fn in (jf.plan, jf.create, jf.find_client_folder):
        assert "search_clients" not in inspect.getsource(fn)


# ── filing under the chosen parent ───────────────────────────────────
def _fields(name="Bell Mountain Middle School"):
    return {"insured_name": name}


def test_without_a_parent_it_lands_at_the_root(share):
    """Today's behaviour, and the bug being fixed."""
    plan = nli.plan_folder(_fields())
    assert plan["mode"] == "new_client"
    assert plan["path"].endswith("Bell Mountain Middle School")


def test_a_chosen_parent_makes_it_a_child(share):
    plan = nli.plan_folder(_fields(), parent="Menifee Union School District")
    assert plan["mode"] == "child"
    assert plan["client"] == "Menifee Union School District"
    assert plan["child"] == "Bell Mountain Middle School"
    assert plan["path"].endswith(
        os.path.join("Menifee Union School District",
                     "Bell Mountain Middle School"))


def test_the_plan_says_the_parent_was_chosen(share):
    """The confirm dialog has to be able to show that this is not where
    the name alone would have put it."""
    plan = nli.plan_folder(_fields(), parent="Menifee Union School District")
    assert plan["parent_chosen"] == "Menifee Union School District"
    assert "parent_chosen" not in nli.plan_folder(_fields())


def test_an_explicit_child_name_still_wins(share):
    plan = nli.plan_folder(_fields(), parent="Menifee Union School District",
                           child="Bell Mountain 8-14-26")
    assert plan["child"] == "Bell Mountain 8-14-26"


def test_creating_under_a_parent_puts_it_on_disk_there(share):
    res = nli.create_folder(_fields(), parent="Val Verde Unified School")
    assert res["ok"]
    assert os.path.isdir(os.path.join(share, "Val Verde Unified School",
                                      "Bell Mountain Middle School"))
    assert not os.path.isdir(os.path.join(share, "Bell Mountain Middle School")), \
        "it must not ALSO appear at the root"


def test_the_pin_points_at_the_child_not_the_umbrella(share, monkeypatch):
    """The audit row is the new loss, so its imports must land in the
    child folder — pinning the umbrella sends them to the wrong place."""
    seen = {}
    import persistence
    monkeypatch.setattr(persistence, "set_folder_path",
                        lambda c, p: seen.update({"client": c, "path": p}))
    nli.create_folder(_fields(), parent="Val Verde Unified School")
    assert seen["client"] == "Bell Mountain Middle School"
    assert seen["path"].endswith(
        os.path.join("Val Verde Unified School", "Bell Mountain Middle School"))


def test_a_blank_parent_changes_nothing(share):
    for blank in ("", "   ", None):
        plan = nli.plan_folder(_fields(), parent=blank)
        assert plan["mode"] == "new_client"


def test_no_insured_and_no_parent_is_still_an_error(share):
    assert nli.plan_folder({})["ok"] is False


# ── ACE is AAA at this office ────────────────────────────────────────
def test_ace_is_folded_to_aaa():
    """Assignments arrive titled ACE; unfolded it splits one carrier
    across two names in every report, filter and chip."""
    import carriers
    assert carriers.normalize("ACE") == "AAA"
    assert carriers.normalize("Ace Insurance") == "AAA"


def test_the_new_loss_parser_normalises_the_carrier():
    """The raw value used to flow straight into the card name."""
    f = nli.parse_assignment_email(
        "From: ACE - Servpro Assignment <no-reply@example.com>\n"
        "Insured Name: Bell Mountain Middle School\n")
    assert f["carrier"] == "AAA"


def test_the_card_name_uses_the_folded_carrier():
    f = nli.parse_assignment_email(
        "From: ACE - Servpro Assignment\nInsured Name: Jane Doe\n")
    assert nli.suggest_card_name(f) == "Jane Doe - AAA"


def test_an_unknown_carrier_is_left_alone():
    """normalize() must not invent a spelling for something it doesn't
    know — that would launder a guess into a fact."""
    f = nli.parse_assignment_email(
        "From: Bilbrey Mutual - Servpro Assignment\nInsured Name: Jane Doe\n")
    assert f["carrier"] == "Bilbrey Mutual"
