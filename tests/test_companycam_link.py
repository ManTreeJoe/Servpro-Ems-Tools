"""Matching CompanyCam projects to jobs.

A wrong pin is worse than no pin: get_link returns the OLDEST row, so a
bad one wins forever. Every guard here comes from a match the first live
dry run actually proposed.
"""
import companycam_link as cl


def _jobs(*names):
    import ems_db_common as C
    return [{"canon_key": C.canon_key(n), "display_name": n} for n in names]


def _projects(*names):
    return [{"id": str(100 + i), "name": n} for i, n in enumerate(names)]


# ── the three differences it has to survive at once ────────────────────

def test_word_order_and_carrier_suffix(_=None):
    """"Michelle Brayley" is "Brayley, Michelle - AAA"."""
    p = cl.plan(_projects("Michelle Brayley"),
                _jobs("Brayley, Michelle - AAA"))
    assert [r["job"] for r in p["link"]] == ["Brayley, Michelle - AAA"]
    assert p["link"][0]["how"] == "tokens"


def test_an_exact_name_still_matches():
    p = cl.plan(_projects("Maria Neeley"), _jobs("Maria Neeley"))
    assert p["link"][0]["how"] == "exact"


def test_a_trailing_date_on_the_job_does_not_block_it():
    p = cl.plan(_projects("Temeku Hills"), _jobs("Temeku Hills (5/20/26)"))
    assert len(p["link"]) == 1


# ── what it must refuse ────────────────────────────────────────────────

def test_a_claim_project_never_lands_on_a_different_claim():
    """The live dry run offered to tie the 1st claim's project to the
    2nd claim's job -- canon_key strips at " - ", so both collapse."""
    p = cl.plan(_projects("Mansolino, Sayra- AAA - 1st Claim"),
                _jobs("Mansolino, Sayra - AAA - 2nd Claim (Kitchen)"))
    assert p["link"] == []
    assert "claim" in p["refused"][0]["reason"]


def test_a_unit_project_never_lands_on_the_parent():
    p = cl.plan(_projects("Aperto Property Management - Unit 214"),
                _jobs("Aperto Property Management"))
    assert p["link"] == []
    assert "parent" in p["refused"][0]["reason"]


def test_a_parent_project_never_lands_on_a_unit():
    p = cl.plan(_projects("Avila Apartments"),
                _jobs("Avila Apartments - Unit 524"))
    assert p["link"] == []


def test_two_candidate_jobs_are_ambiguous_not_a_coin_flip():
    """Duplicate job rows are real -- 'Feivelson, David - Mercury' and
    'Feivelson David' both exist."""
    p = cl.plan(_projects("David Feivelson"),
                _jobs("Feivelson, David - Mercury", "Feivelson David"))
    assert p["link"] == []
    assert len(p["ambiguous"][0]["jobs"]) == 2


def test_no_match_is_reported_not_forced():
    p = cl.plan(_projects("Somebody Unknown"), _jobs("Brayley, Michelle"))
    assert [r["project"] for r in p["unmatched"]] == ["Somebody Unknown"]


def test_an_already_linked_job_is_not_relinked():
    import ems_db_common as C
    key = C.canon_key("Brayley, Michelle - AAA")
    p = cl.plan(_projects("Michelle Brayley"),
                _jobs("Brayley, Michelle - AAA"), linked_keys={key})
    assert p["link"] == []
    assert len(p["already"]) == 1


def test_matching_units_are_allowed():
    p = cl.plan(_projects("Avila Apartments Unit 524"),
                _jobs("Avila Apartments - Unit 524"))
    assert len(p["link"]) == 1


def test_planning_writes_nothing(monkeypatch):
    import ems_db
    monkeypatch.setattr(ems_db, "set_link",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("plan wrote")))
    cl.plan(_projects("Michelle Brayley"), _jobs("Brayley, Michelle - AAA"))


def test_two_sites_under_one_client_are_not_the_same_job():
    """canon_key strips at " - ", so "PCM - Kellogg Terrace" and
    "PCM - (Gianni Villas)" both reduce to "pcm" and looked exact."""
    p = cl.plan(_projects("PCM - Kellogg Terrace Condominiums"),
                _jobs("PCM  - (Gianni Villas) - 6/15/26"))
    assert p["link"] == []
    assert "disagree after the dash" in p["refused"][0]["reason"]


def test_a_shorter_name_is_not_a_disagreement():
    """One side saying nothing after the dash is just a shorter name."""
    p = cl.plan(_projects("Gabi Campbell"),
                _jobs("Gabi Campbell - Progressive"))
    assert len(p["link"]) == 1


def test_a_shared_word_after_the_dash_is_enough():
    p = cl.plan(_projects("HABIBOLLAH SHARIFZADEH - Mercury"),
                _jobs("HABIBOLLAH SHARIFZADEH - Mercury"))
    assert len(p["link"]) == 1


def test_two_projects_cannot_both_claim_one_job():
    """The folder rename made this exact mistake on this exact client:
    each candidate was checked against the jobs and never against the
    other candidates."""
    p = cl.plan(_projects("Jennifer Parks", "Jennifer Parks -Self Pay"),
                _jobs("Parks, Jennifer - AAA"))
    assert p["link"] == []
    assert len(p["ambiguous"]) == 1
    assert "more than one project" in p["ambiguous"][0]["reason"]
