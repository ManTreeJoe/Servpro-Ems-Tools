"""Merging duplicate job rows must never merge two CLAIMS.

canon_key strips at " - ", so every claim of one client collapses to the
same key and two genuinely different losses look like a duplicate row.
Merging those is not a tidy-up, it is one claim absorbing another.
"""
import os

import merge_duplicate_jobs as m


def test_a_folder_of_claim_subfolders_is_a_client_not_a_duplicate(tmp_path):
    """Sayra Mansolino: one folder holding 1st, 2nd and 3rd Claim."""
    root = tmp_path / "mansolino sayra"
    for d in ("1st Claim", "2nd Claim (KItchen)", "3rd Claim 7-29-2026"):
        (root / d).mkdir(parents=True)
    why = m.claim_evidence(
        ["Mansolino, Sayra - AAA - 2nd Claim (Kitchen)", "mansolino sayra"],
        [str(root)])
    assert "claim subfolders" in why


def test_a_claim_marked_name_is_held_back(tmp_path):
    why = m.claim_evidence(["Neeley, Maria - AAA (2nd Claim)", "Maria Neeley"],
                           [])
    assert "specific claim" in why


def test_a_plain_duplicate_pair_is_allowed(tmp_path):
    root = tmp_path / "cross heather"
    (root / "EMS").mkdir(parents=True)
    assert m.claim_evidence(["Cross, Heather  - AAA", "cross heather"],
                            [str(root)]) == ""


def test_one_claim_subfolder_is_not_enough(tmp_path):
    """A single 'Second Claim' folder beside the main work is the normal
    shape of ONE job, not evidence of two rows worth keeping apart."""
    root = tmp_path / "someone"
    (root / "2nd Claim").mkdir(parents=True)
    assert m.claim_evidence(["Someone - AAA", "someone"], [str(root)]) == ""


def test_a_missing_folder_does_not_crash(tmp_path):
    assert m.claim_evidence(["A", "a"], [str(tmp_path / "nope")]) == ""


def test_held_pairs_are_excluded_from_the_apply(monkeypatch, capsys):
    """The guard has to actually gate the write, not just print."""
    rows = [
        {"into": "a", "into_name": "A", "from": ["a2"], "from_names": ["a2"],
         "links": {}, "hold": ""},
        {"into": "b", "into_name": "B (2nd Claim)", "from": ["b2"],
         "from_names": ["b2"], "links": {}, "hold": "named for a specific claim"},
    ]
    monkeypatch.setattr(m, "plan", lambda: (rows, {}))
    merged = []
    monkeypatch.setattr(m.ems_db, "merge_jobs",
                        lambda into, frm, **k: merged.append(into) or {"undo_id": "u1"})
    monkeypatch.setattr(m, "UNDO_LOG", str(os.devnull))
    monkeypatch.setattr(m.sys, "argv", ["x", "--apply"])
    m.main()
    assert merged == ["a"], "a held pair was merged anyway"
