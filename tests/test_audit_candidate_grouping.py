"""Audit-one-job picker: variants of ONE job collapse into a single
combined candidate (token-set + carrier-strip + superset-fold), so a
misspelled / reordered / carrier-suffixed spelling stops showing as its
own row. Regression for the 'Ensign' case (Kathy x2, Michael x3 -> 2)."""
import audit_web as aw


def _raw(name, source, path="", score=25, has_card=False, detail=""):
    return {"name": name, "source": source, "detail": detail,
            "path": path, "score": score, "has_card": has_card}


def test_ensign_case_collapses_to_two():
    raw = [
        _raw("Kathy Ensign", "run", score=30),
        _raw("Ensign Kathy", "folder", path=r"X:\2026\Ensign Kathy", score=20),
        _raw("Ensign, Michael", "pin", path=r"X:\2026\Ensign Michael",
             score=25, has_card=True),
        _raw("Ensign, Michael-Mercury", "pin", score=25, has_card=True),
        _raw("Michael Ensign", "pin", score=25, has_card=True),
    ]
    cands = aw._group_audit_candidates(raw)
    assert len(cands) == 2                       # Kathy + Michael, not 5
    by_key = {frozenset(aw._candidate_group_key(c["name"])): c for c in cands}
    assert frozenset({"ensign", "kathy"}) in by_key
    assert frozenset({"ensign", "michael"}) in by_key


def test_most_complete_variant_wins():
    raw = [
        _raw("Kathy Ensign", "run", score=30),                 # no folder
        _raw("Ensign Kathy", "folder", path=r"X:\f", score=20),  # has folder
    ]
    (c,) = aw._group_audit_candidates(raw)
    assert c["name"] == "Ensign Kathy"           # folder variant wins
    assert c["path"] == r"X:\f"
    assert set(c["sources"]) == {"run", "folder"}   # both sources merged
    assert c["mergeable"] is True
    assert sorted(c["variants"]) == ["Ensign Kathy", "Kathy Ensign"]


def test_carrier_suffix_folds_in():
    raw = [
        _raw("Ensign, Michael", "pin", path=r"X:\m", has_card=True),
        _raw("Ensign, Michael-Mercury", "pin", has_card=True),
        _raw("Michael Ensign", "pin", has_card=True),
    ]
    (c,) = aw._group_audit_candidates(raw)
    assert len(c["variants"]) == 3
    assert c["has_card"] is True
    assert c["name"] == "Ensign, Michael"        # the one with folder+card


def test_same_last_name_stays_separate():
    # Different first names → different jobs, even sharing a surname.
    raw = [_raw("Kathy Ensign", "run"), _raw("Michael Ensign", "pin",
                                             has_card=True)]
    cands = aw._group_audit_candidates(raw)
    assert len(cands) == 2


def test_lone_candidate_not_mergeable():
    (c,) = aw._group_audit_candidates([_raw("Sanchez, Anthony", "folder",
                                            path=r"X:\s", score=40)])
    assert c["mergeable"] is False
    assert c["variants"] == ["Sanchez, Anthony"]
