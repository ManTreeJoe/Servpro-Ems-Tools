"""Tech-name detection — locks in the recognized roster + initials so a
regex tweak doesn't silently drop a tech (PCB and Pris?cilla are common
gotchas)."""
from audit_logic import TECH_PATTERN, ABBREV


def _matches(text):
    return [m.group(0) for m in TECH_PATTERN.finditer(text)]


def test_full_names():
    assert "Cesar" in _matches("Cesar arrived at 9am")
    assert "Vince" in _matches("Vince/Wendy on cleanup")
    assert "Priscilla" in _matches("Priscilla 1st run")


def test_priscilla_misspelling():
    # Common SERVPRO note typo — must still be caught
    assert _matches("Pricilla, Wendy 1st run") != []


def test_initials_only():
    for initial in ("FB", "ML", "ME", "GL", "PG", "JL", "AP", "PCB"):
        hits = _matches(f"Crew today: {initial}/Wendy")
        assert hits, f"Initials {initial!r} not detected"


def test_pcb_distinct_from_other_words():
    # Word-boundaries should keep PCB separate from "PCBs" (plural) etc.
    # We accept the bare token; this test guards against ever stripping it.
    assert _matches("Crew: PCB and Wendy")


def test_initials_map_back_to_a_real_name():
    for k in ("FB", "ML", "ME", "GL", "PG", "JL", "AP"):
        assert ABBREV[k]


def test_jl_and_ap_do_not_collapse_to_other_techs():
    """JL is its own person — must NOT be expanded to Jose. AP is also
    its own person without a folder — must NOT be expanded to Aaron
    Perret. Used to route JL's jobs into Jose's folder otherwise."""
    assert ABBREV["JL"] == "JL"
    assert ABBREV["AP"] == "AP"
    assert "Jose" not in {ABBREV.get("JL")}
    assert "Aaron Perret" not in {ABBREV.get("AP")}
