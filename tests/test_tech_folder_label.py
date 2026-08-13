"""How a tech is written on a photo folder.

Only the seven leads collapse to initials — FB, ME, ML, RQ, PG, AP, JL —
because those are the codes the office has read at a glance for years.
Everyone else is "First LastInitial": "Nestor Bautista" is "Nestor B".

`initials_for_name` falls back to first+last initial for ANY multi-word
name, so helpers were being filed as NB / DR / JR / MC / VG — codes for
people nobody thinks of that way. The zip import's own note says the rule
was always leads-only; the fallback quietly overrode it.
"""
import pytest

import audit_logic as al


LEADS = [
    ("Fernando Baca",  "FB"),
    ("Mark Escobar",   "ME"),
    ("Mark Lingurar",  "ML"),
    ("Rudy Q",         "RQ"),
    ("Pablo G",        "PG"),
    ("Aaron P",        "AP"),
    ("Johnny L",       "JL"),
]


@pytest.mark.parametrize("name,want", LEADS)
def test_the_seven_leads_are_initials(name, want):
    assert al.tech_folder_label(name) == want


@pytest.mark.parametrize("name,want", [
    ("Nestor Bautista", "Nestor B"),
    ("Danny Ruiz",      "Danny R"),
    ("Jose Ramirez",    "Jose R"),
    ("Maria Gonzalez",  "Maria G"),
])
def test_everyone_else_is_first_name_last_initial(name, want):
    assert al.tech_folder_label(name) == want


def test_a_helper_is_never_reduced_to_two_letters():
    """The whole complaint: NB / DR / JR mean nothing to anyone."""
    for name in ("Nestor Bautista", "Danny Ruiz", "Jose Ramirez"):
        got = al.tech_folder_label(name)
        assert len(got) > 2 and " " in got


def test_a_single_word_name_is_left_alone():
    """"Danny" is already how he's known — adding an initial invents one."""
    assert al.tech_folder_label("Danny") == "Danny"


def test_an_unrecognised_code_is_not_mangled():
    """A folder already labelled with an initials code we don't know must
    not be rewritten into something new — that splits a job's photos
    across two spellings."""
    assert al.tech_folder_label("DR") == "DR"


def test_blank_in_blank_out():
    assert al.tech_folder_label("") == ""
    assert al.tech_folder_label(None) == ""
    assert al.tech_folder_label("   ") == ""


def test_whitespace_is_collapsed():
    assert al.tech_folder_label("  Nestor   Bautista ") == "Nestor B"


def test_a_lead_written_as_initials_stays_that_way():
    assert al.tech_folder_label("FB") == "FB"
    assert al.tech_folder_label("ME") == "ME"


def test_both_photo_paths_use_the_same_label():
    """The CompanyCam pull and the zip import must agree, or one tech ends
    up with two folders on one job."""
    import inspect
    import companycam_api
    import audit_web
    assert "tech_folder_label" in inspect.getsource(companycam_api.tech_label)
    src = inspect.getsource(audit_web)
    assert "audit_logic.tech_folder_label" in src


def test_lead_roster_is_still_the_seven():
    """If someone joins or leaves the leads, this test should be the thing
    that makes them think about the folders already on the share."""
    assert set(al.TECH_LEADS) == {
        "Fernando", "Rudy", "Pablo", "Mark E", "Mark L", "Aaron", "Johnny"}
