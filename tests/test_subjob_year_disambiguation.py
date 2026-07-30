"""Commercial sub-job parents must resolve against the CURRENT year.

Live bug: `_match_tokens` matches on any two shared tokens, so every
"<Name> Property Management" folder matched all the others. With more than
one match the year loop treated the current year as unresolved and fell
through to the PRIOR year — auditing a 2026 commercial job against its 2025
folder. An exact name match among the fuzzy ones is not ambiguous, so it
wins.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_logic as al


def _mk_job(root, name, subs=()):
    """A job folder, optionally with named sub-job folders inside."""
    p = os.path.join(root, name)
    os.makedirs(os.path.join(p, "EMS", "PICS"), exist_ok=True)
    for s in subs:
        os.makedirs(os.path.join(p, s, "EMS", "PICS"), exist_ok=True)
    return p


@pytest.fixture
def share(tmp_path):
    base = tmp_path / "IE_Public"
    cur = base / "2026 Jobs"
    prev = base / "2025 Jobs"
    cur.mkdir(parents=True)
    prev.mkdir(parents=True)
    return base, str(cur), str(prev)


# ── the matcher's own collision behaviour ───────────────────────────────

def test_generic_tokens_make_unrelated_companies_collide():
    """Documents WHY the fix is needed — two shared tokens is enough."""
    a = al._norm_folder("JLA PROPERTY MANAGEMENT")
    b = al._norm_folder("MGR Property Management")
    assert al._match_tokens_folder(al._toks_folder(b), al._toks_folder(a))


def test_exact_normalized_name_picks_one_out_of_many():
    names = ["Action Property Management", "JLA PROPERTY MANAGEMENT",
             "MGR Property Management", "Next Door Property Management"]
    nl = al._norm_folder("JLA Property Management")
    exact = [f for f in names if al._norm_folder(f) == nl]
    assert exact == ["JLA PROPERTY MANAGEMENT"]


# ── end-to-end through audit_jobs ───────────────────────────────────────

def _run(base, client):
    res, err = al.audit_jobs([{"client": client, "section": "work",
                               "raw": "", "techs": []}],
                             audit_base=str(base), year=2026,
                             use_cache=False, expand_subjobs=True)
    assert not err, err
    return res or []


def test_commercial_parent_resolves_to_current_year(share):
    """The reported bug: same-named commercial parents in both years, and
    several look-alike companies in 2026 to force the ambiguity."""
    base, cur, prev = share
    for n in ("Action Property Management", "MGR Property Management",
              "Next Door Property Management"):
        _mk_job(cur, n)
    _mk_job(cur, "JLA Property Management", ["Site A", "Site B"])
    _mk_job(prev, "JLA Property Management", ["Old Site 1", "Old Site 2"])

    rows = _run(base, "JLA Property Management")
    paths = [r.get("path") or "" for r in rows if r.get("path")]
    assert paths, "no folder resolved at all"
    assert all("2026 Jobs" in p for p in paths), (
        f"resolved against the wrong year: {paths}")
    assert not any("2025 Jobs" in p for p in paths)


def test_unambiguous_parent_still_resolves(share):
    """The narrowing must not break the ordinary single-match case."""
    base, cur, _ = share
    _mk_job(cur, "Menifee Union School District", ["Campus A", "Campus B"])
    rows = _run(base, "Menifee Union School District")
    assert any("2026 Jobs" in (r.get("path") or "") for r in rows)


def test_prior_year_fallback_survives_for_a_genuine_old_job(share):
    """A job that only exists in 2025 must still be found — the fix
    narrows ambiguity, it does not remove the year fallback."""
    base, cur, prev = share
    _mk_job(cur, "Someone Else")
    _mk_job(prev, "Carryover Commercial", ["Site A", "Site B"])
    rows = _run(base, "Carryover Commercial")
    paths = [r.get("path") or "" for r in rows if r.get("path")]
    assert any("2025 Jobs" in p for p in paths), paths


def test_no_exact_match_leaves_it_ambiguous(share):
    """Two look-alikes and no exact hit: stay ambiguous rather than guess."""
    base, cur, _ = share
    _mk_job(cur, "Alpha Property Management", ["A", "B"])
    _mk_job(cur, "Beta Property Management", ["C", "D"])
    rows = _run(base, "Gamma Property Management")
    for r in rows:
        assert not r.get("subjob"), "guessed a parent it shouldn't have"
