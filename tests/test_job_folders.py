"""`year → client → child` folder creation.

User rule: a client gets ONE folder. A second claim, a unit, or a
commercial sub-job is a CHILD inside it — never a second top-level folder.
Claims / units / sub-jobs are the same structure, so there's one code path.

Folder-name shapes and the "no claim children means the root IS claim 1"
convention are taken from the live share (Calderon Edilson has only a
'2nd Claim'; Mansolino Sayra has 1st/2nd/3rd).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import job_folders as jf


@pytest.fixture
def base(tmp_path):
    (tmp_path / "2026 Jobs").mkdir()
    (tmp_path / "2025 Jobs").mkdir()
    (tmp_path / "2026 LA FIRES").mkdir()
    return str(tmp_path)


def _client(base, name, children=()):
    d = os.path.join(base, "2026 Jobs", name)
    os.makedirs(os.path.join(d, "EMS", "PICS"), exist_ok=True)
    for c in children:
        os.makedirs(os.path.join(d, c, "EMS"), exist_ok=True)
    return d


# ── ordinals ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n,s", [(1, "1st"), (2, "2nd"), (3, "3rd"),
                                 (4, "4th"), (11, "11th"), (12, "12th"),
                                 (13, "13th"), (21, "21st"), (22, "22nd")])
def test_ordinal(n, s):
    assert jf.ordinal(n) == s


@pytest.mark.parametrize("name,n", [
    ("1st Claim", 1), ("2nd claim", 2), ("3rd Claim", 3),
    ("2nd Claim (KItchen)", 2),         # real folder on the share
    ("3rd Claim 7-29-2026", 3),         # real folder on the share
    ("Second Claim", 2),
    ("Unit 182", None), ("Coreland Company unit 121", None), ("EMS", None),
])
def test_claim_ordinal_of(name, n):
    assert jf.claim_ordinal_of(name) == n


# ── year folder ─────────────────────────────────────────────────────────

def test_year_dir_finds_current_year(base):
    assert jf.year_dir(base=base, year=2026).endswith("2026 Jobs")


def test_year_dir_skips_la_fires(base):
    """'2026 LA FIRES' also carries the year — same exclusion audit_logic
    uses, or half the jobs would resolve into the fire folder."""
    got = os.path.basename(jf.year_dir(base=base, year=2026))
    assert got == "2026 Jobs" and "FIRE" not in got.upper()


def test_year_dir_missing(base):
    assert jf.year_dir(base=base, year=1999) == ""


# ── finding the client ──────────────────────────────────────────────────

def test_find_client_is_case_and_punctuation_insensitive(base):
    _client(base, "Riley, Robert")
    assert jf.find_client_folder("riley robert", base=base, year=2026)
    assert jf.find_client_folder("RILEY,  ROBERT", base=base, year=2026)


def test_find_client_never_matches_fuzzily(base):
    """The bug this exists to avoid: audit_logic's token matcher counts any
    two shared words, so every '<X> Property Management' matched all the
    others. Creating a folder on that basis would nest a new customer
    inside an unrelated job."""
    _client(base, "JLA Property Management")
    assert jf.find_client_folder("MGR Property Management",
                                 base=base, year=2026) == ""


def test_find_client_absent(base):
    assert jf.find_client_folder("Nobody", base=base, year=2026) == ""


# ── new client ──────────────────────────────────────────────────────────

def test_creates_a_new_client_folder_with_skeleton(base):
    res = jf.create("Newman, Paul", base=base, year=2026)
    assert res["ok"] and res["mode"] == "new_client" and res["created"]
    assert os.path.isdir(os.path.join(res["path"], "EMS", "PICS"))
    assert os.path.isdir(os.path.join(res["path"], "EMS", "DOCS"))


def test_illegal_characters_are_sanitized(base):
    res = jf.create('Bad:Name/With*Chars', base=base, year=2026)
    assert res["ok"]
    assert not set(os.path.basename(res["path"])) & set(':/*?"<>|\\')


def test_blank_client_rejected(base):
    assert not jf.create("   ", base=base, year=2026)["ok"]


# ── existing client → child ─────────────────────────────────────────────

def test_existing_client_gets_a_child_not_a_second_top_level_folder(base):
    """The whole point of the task."""
    _client(base, "Riley, Robert")
    res = jf.create("Riley, Robert", base=base, year=2026)
    assert res["ok"] and res["mode"] == "child"
    assert os.path.basename(os.path.dirname(res["path"])) == "Riley, Robert"
    year = os.path.join(base, "2026 Jobs")
    assert len([d for d in os.listdir(year)]) == 1, "no duplicate client folder"


def test_named_child_is_used_verbatim_for_a_unit(base):
    _client(base, "Metro at Main", ["Unit 182"])
    res = jf.create("Metro at Main", child="Unit 214", base=base, year=2026)
    assert res["ok"] and res["child"] == "Unit 214"
    assert res["path"].endswith(os.path.join("Metro at Main", "Unit 214"))


def test_named_child_works_for_a_commercial_subjob(base):
    _client(base, "Next Door Property Management")
    res = jf.create("Next Door Property Management",
                    child="Coreland Company unit 121", base=base, year=2026)
    assert res["ok"] and res["child"] == "Coreland Company unit 121"


def test_second_claim_when_no_claim_children_exist(base):
    """Live convention: the original claim's files sit at the client root,
    so the FIRST added claim folder is '2nd Claim' (cf. Calderon Edilson)."""
    _client(base, "Calderon Edilson")
    res = jf.create("Calderon Edilson", base=base, year=2026)
    assert res["child"] == "2nd Claim"


def test_next_claim_follows_the_highest_existing(base):
    _client(base, "Mansolino Sayra",
            ["1st Claim", "2nd Claim (KItchen)", "3rd Claim 7-29-2026"])
    res = jf.create("Mansolino Sayra", base=base, year=2026)
    assert res["child"] == "4th Claim"


def test_second_claim_flag_overrides_a_supplied_name(base):
    _client(base, "Riley, Robert", ["1st Claim", "2nd Claim"])
    res = jf.create("Riley, Robert", child="Whatever", second_claim=True,
                    base=base, year=2026)
    assert res["child"] == "3rd Claim"


def test_unit_children_do_not_count_as_claims(base):
    _client(base, "Metro at Main", ["Unit 182", "Unit 188", "Unit 237"])
    res = jf.create("Metro at Main", base=base, year=2026)
    assert res["child"] == "2nd Claim"


def test_skeleton_dirs_are_not_mistaken_for_children(base):
    _client(base, "Solo Job")     # has EMS/PICS only
    assert jf.list_children(os.path.join(base, "2026 Jobs", "Solo Job")) == []


def test_existing_child_is_refused_not_overwritten(base):
    _client(base, "Metro at Main", ["Unit 182"])
    res = jf.create("Metro at Main", child="Unit 182", base=base, year=2026)
    assert not res["ok"] and res["exists"] and not res["created"]


# ── plan is read-only ───────────────────────────────────────────────────

def test_plan_creates_nothing(base):
    _client(base, "Riley, Robert")
    p = jf.plan("Riley, Robert", base=base, year=2026)
    assert p["mode"] == "child" and p["child"] == "2nd Claim"
    assert not os.path.isdir(p["path"])


def test_plan_reports_existing_children_for_the_confirm_dialog(base):
    _client(base, "Metro at Main", ["Unit 182", "Unit 188"])
    p = jf.plan("Metro at Main", child="Unit 214", base=base, year=2026)
    assert p["children"] == ["Unit 182", "Unit 188"]


# ── promoting the root into "1st Claim" ─────────────────────────────────

def test_promote_is_offered_when_no_claim_folders_exist(base):
    """Calderon Edilson's shape: EMS at the root, one '2nd Claim' child."""
    d = _client(base, "Calderon Edilson")
    p = jf.plan_promote_first_claim(d)
    assert p["eligible"] and p["moves"] == ["EMS"]
    assert p["target"].endswith("1st Claim")


def test_promote_offered_even_when_another_claim_folder_exists(base):
    """Calderon Edilson's exact shape — root EMS (claim 1) beside a
    '2nd Claim'. An earlier "skip if any claim exists" rule read this, the
    very case the feature is for, as ineligible."""
    d = _client(base, "Calderon Edilson", ["2nd Claim"])
    p = jf.plan_promote_first_claim(d)
    assert p["eligible"] and p["moves"] == ["EMS"]


def test_client_level_docs_are_never_swept_into_a_claim(base):
    """Mansolino Sayra keeps DOCS at the root, Szynal Donna FIELD DOCS —
    paperwork shared by every claim. Only job containers move."""
    d = os.path.join(base, "2026 Jobs", "Mansolino Sayra")
    os.makedirs(os.path.join(d, "2nd Claim", "EMS"), exist_ok=True)
    os.makedirs(os.path.join(d, "DOCS"), exist_ok=True)
    os.makedirs(os.path.join(d, "FIELD DOCS"), exist_ok=True)
    p = jf.plan_promote_first_claim(d)
    assert not p["eligible"], "nothing at this root belongs to one claim"
    assert p["moves"] == []


def test_promote_refused_when_first_claim_already_exists(base):
    d = _client(base, "Riley, Robert", ["1st Claim", "2nd Claim"])
    p = jf.plan_promote_first_claim(d)
    assert not p["eligible"] and "already exists" in p["reason"]


def test_loose_root_files_move_only_when_no_claims_exist(base):
    """With claims already present, a stray root file is client-level."""
    d = _client(base, "Has Claims", ["2nd Claim"])
    open(os.path.join(d, "note.txt"), "w").close()
    assert "note.txt" not in jf.plan_promote_first_claim(d)["moves"]
    d2 = _client(base, "No Claims")
    open(os.path.join(d2, "note.txt"), "w").close()
    assert "note.txt" in jf.plan_promote_first_claim(d2)["moves"]


# ── context for the "New claim?" toggle ─────────────────────────────────

def test_context_reports_claims_and_children(base):
    d = _client(base, "Metro at Main", ["Unit 182", "1st Claim"])
    ctx = jf.client_context("Metro at Main", d)
    assert ctx["has_folder"]
    assert ctx["claims"] == ["1st Claim"]
    assert "Unit 182" in ctx["children"]
    assert ctx["suggest_new_claim"] is True


def test_context_for_a_brand_new_client_suggests_nothing(base, monkeypatch):
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name", lambda n, **k: None)
    ctx = jf.client_context("Nobody At All", "")
    assert not ctx["has_folder"] and ctx["suggest_new_claim"] is False


def test_context_suggests_a_claim_from_trello_alone(base, monkeypatch):
    """Prior work isn't only folders — a client can have a card and a
    CompanyCam project before any folder exists."""
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name",
                        lambda n, **k: {"canon_key": "k", "display_name": "K"})
    monkeypatch.setattr(ems_db, "get_links",
                        lambda k, t: [{"link_value": "card1"}])
    monkeypatch.setattr(ems_db, "get_link", lambda k, t: "cc-proj")
    ctx = jf.client_context("Some Client", "")
    assert ctx["known"] and ctx["cards"] == ["card1"]
    assert ctx["companycam"] == "cc-proj"
    assert ctx["suggest_new_claim"] is True


def test_plan_exposes_context_for_both_modes(base):
    _client(base, "Riley, Robert")
    assert "context" in jf.plan("Riley, Robert", base=base, year=2026)
    assert "context" in jf.plan("Brand New", base=base, year=2026)


def test_promote_ignores_non_job_folders(base):
    d = _client(base, "Someone")
    os.makedirs(os.path.join(d, "FIELD DOCS"), exist_ok=True)
    p = jf.plan_promote_first_claim(d)
    assert "EMS" in p["moves"] and "FIELD DOCS" not in p["moves"]


def test_promote_moves_content_and_leaves_siblings(base):
    d = _client(base, "Calderon Edilson")
    open(os.path.join(d, "note.txt"), "w").close()
    res = jf.promote_first_claim(d, repin=False)
    assert res["ok"] and res["created"]
    assert os.path.isdir(os.path.join(d, "1st Claim", "EMS", "PICS"))
    assert os.path.isfile(os.path.join(d, "1st Claim", "note.txt"))
    assert not os.path.exists(os.path.join(d, "EMS"))


def test_promote_then_create_gives_two_sibling_claims(base):
    d = _client(base, "Calderon Edilson")
    res = jf.create("Calderon Edilson", base=base, year=2026,
                    promote_first=True)
    assert res["ok"] and res["child"] == "2nd Claim"
    kids = sorted(jf.list_children(d))
    assert kids == ["1st Claim", "2nd Claim"]


def test_promote_rolls_back_when_a_move_fails(base, monkeypatch):
    """A locked file must not leave the job split across two folders."""
    import shutil
    d = _client(base, "Calderon Edilson")
    os.makedirs(os.path.join(d, "CONTENTS"), exist_ok=True)
    real = shutil.move
    calls = {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("locked by another process")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "move", flaky)
    res = jf.promote_first_claim(d, repin=False)
    assert not res["ok"] and "rolled back" in res["reason"]
    assert os.path.isdir(os.path.join(d, "EMS"))
    assert os.path.isdir(os.path.join(d, "CONTENTS"))
    assert not os.path.exists(os.path.join(d, "1st Claim"))


def test_plan_offers_promotion_without_doing_it(base):
    d = _client(base, "Calderon Edilson")
    p = jf.plan("Calderon Edilson", base=base, year=2026)
    assert p["promote_first_claim"]["eligible"]
    assert os.path.isdir(os.path.join(d, "EMS")), "plan must not move anything"


def test_promote_is_off_by_default(base):
    d = _client(base, "Calderon Edilson")
    jf.create("Calderon Edilson", base=base, year=2026)
    assert os.path.isdir(os.path.join(d, "EMS")), "must not move without asking"


def test_unit_structured_client_is_never_promoted(base):
    """Metro at Main: Unit 182/188 children plus a CHECK pdf and prelims at
    the root. Those cover the whole property — sweeping them into a
    '1st Claim' folder would file a payment under one unit's claim."""
    d = _client(base, "Metro at Main", ["Unit 182", "Unit 188"])
    open(os.path.join(d, "CHECK 8506962186 $15549.81.pdf"), "w").close()
    open(os.path.join(d, "METRO_AT_MAIN-PRE-LIM-1.pdf"), "w").close()
    p = jf.plan_promote_first_claim(d)
    assert not p["eligible"] and "units/sub-jobs" in p["reason"]
    assert p["moves"] == []


def test_commercial_subjob_client_is_never_promoted(base):
    d = _client(base, "Next Door Property Management",
                ["Coreland Company unit 121"])
    assert not jf.plan_promote_first_claim(d)["eligible"]


def test_loose_files_are_left_when_the_client_has_any_child(base):
    d = _client(base, "Calderon Edilson", ["2nd Claim"])
    open(os.path.join(d, "client level.pdf"), "w").close()
    p = jf.plan_promote_first_claim(d)
    assert p["eligible"] and p["moves"] == ["EMS"]
    assert "client level.pdf" not in p["moves"]


# ── the New Loss dialog contract ────────────────────────────────────────

def test_property_management_client_gets_a_named_child(base):
    """Action Property Management's real shape: a corporate client that
    accrues one child per claim/tenant. A new loss for one of their
    tenants must file INSIDE them, not as a second top-level folder —
    which is exactly how 'Mendiola Mary' ended up loose on the share."""
    _client(base, "Action Property Management", ["Garage Door", "Villaigo"])
    res = jf.create("Action Property Management", child="Mendiola Mary",
                    base=base, year=2026)
    assert res["ok"] and res["mode"] == "child"
    assert res["path"].endswith(
        os.path.join("Action Property Management", "Mendiola Mary"))
    year = os.path.join(base, "2026 Jobs")
    assert os.listdir(year) == ["Action Property Management"], \
        "no second top-level folder"


def test_plan_is_stable_when_called_repeatedly(base):
    """The dialog re-plans on every keystroke-ish event; planning must not
    create anything or drift."""
    _client(base, "Riley, Robert", ["1st Claim", "2nd Claim"])
    a = jf.plan("Riley, Robert", base=base, year=2026)
    b = jf.plan("Riley, Robert", base=base, year=2026)
    assert a["child"] == b["child"] == "3rd Claim"
    assert not os.path.isdir(a["path"])


def test_named_child_wins_unless_second_claim_is_set(base):
    _client(base, "Riley, Robert", ["1st Claim"])
    named = jf.plan("Riley, Robert", child="Unit 5", base=base, year=2026)
    assert named["child"] == "Unit 5"
    forced = jf.plan("Riley, Robert", child="Unit 5", second_claim=True,
                     base=base, year=2026)
    assert forced["child"] == "2nd Claim"
