"""Multi-claim subfolder detection.

Real-world case (Sayra Mansolino, 2026): one top-level job folder holds
two claim SUBfolders — "1st Claim" and "2nd Claim (KItchen)". The daily
audit has to descend into the active (highest-numbered) claim folder so
EMS / PICS / DOCS lookups land on the right paperwork.

The parser originally only knew ordinals second..fifth and required the
folder name to END at "claim", so BOTH of these real folders parsed to
None: "1st Claim" (no "1st"/"first" ordinal) and "2nd Claim (KItchen)"
(trailing parenthetical descriptor broke the `$` anchor). The audit then
sat on the empty parent and flagged everything missing.

Pinning the cases here so a regex tweak can't silently re-break it."""
import audit_logic as a


def test_first_claim_ordinal_recognized():
    # "1st" / "first" / "one" all resolve to claim 1.
    assert a._claim_number_from_folder("1st Claim") == 1
    assert a._claim_number_from_folder("First Claim") == 1


def test_trailing_parenthetical_descriptor_allowed():
    # The user appends a room descriptor — "(Kitchen)" — to disambiguate
    # claims. That must NOT defeat detection.
    assert a._claim_number_from_folder("2nd Claim (KItchen)") == 2
    assert a._claim_number_from_folder("Claim #3 (Roof)") == 3


def test_higher_ordinals_still_work():
    assert a._claim_number_from_folder("Second Claim") == 2
    assert a._claim_number_from_folder("Claim 2") == 2
    assert a._claim_number_from_folder("Third Claim") == 3


def test_sub_assets_and_unrelated_folders_rejected():
    # A non-parenthetical trailing word marks a sub-asset of the claim
    # (e.g. "Second Claim Photos"), not the claim folder itself.
    assert a._claim_number_from_folder("Second Claim Photos") is None
    assert a._claim_number_from_folder("Claim Notes") is None
    assert a._claim_number_from_folder("EMS") is None
    assert a._claim_number_from_folder("PICS") is None


def test_find_latest_descends_into_active_claim(tmp_path):
    job = tmp_path / "Mansolino Sayra"
    (job / "1st Claim").mkdir(parents=True)
    (job / "2nd Claim (KItchen)").mkdir()
    # Picks the highest-numbered claim — the active one.
    assert a.find_latest_claim_subfolder(str(job)) == "2nd Claim (KItchen)"


def test_find_latest_none_when_no_claim_subfolder(tmp_path):
    job = tmp_path / "Some Job"
    (job / "EMS").mkdir(parents=True)
    (job / "PICS").mkdir()
    assert a.find_latest_claim_subfolder(str(job)) is None


# ── audit_jobs expansion: one job folder, multiple claim SUBfolders ──

def _setup(tmp_path, year, layout):
    """layout = {job_folder: [subfolder, …]}. Returns the audit base."""
    base = tmp_path / "audit_base"
    yd = base / str(year)
    for job, subs in layout.items():
        for sub in subs:
            (yd / job / sub).mkdir(parents=True)
        if not subs:
            (yd / job).mkdir(parents=True)
    return str(base)


def test_two_claim_subfolders_expand_to_two_rows(tmp_path):
    base = _setup(tmp_path, 2026, {
        "Mansolino Sayra": ["1st Claim", "2nd Claim (KItchen)"],
    })
    rows, _err = a.audit_jobs(
        [{"client": "Mansolino Sayra", "techs": []}], base, year=2026)
    # One row per claim.
    assert len(rows) == 2
    clients = {r["client"] for r in rows}
    assert clients == {
        "Mansolino Sayra 1st Claim",
        "Mansolino Sayra 2nd Claim (KItchen)",
    }
    # Both trace back to the single run-doc job for result↔job pairing.
    assert all(r.get("claim_origin") == "Mansolino Sayra" for r in rows)
    # Each row's audited folder is the parent \ its own claim subfolder.
    folders = {r["folder"] for r in rows}
    assert folders == {
        "Mansolino Sayra \\ 1st Claim",
        "Mansolino Sayra \\ 2nd Claim (KItchen)",
    }
    assert all(r.get("found") for r in rows)


def test_single_claim_subfolder_stays_one_row(tmp_path):
    # Only one claim subfolder → no expansion; the audit still descends
    # into it (existing latest-claim behavior).
    base = _setup(tmp_path, 2026, {
        "Mansolino Sayra": ["2nd Claim (KItchen)"],
    })
    rows, _err = a.audit_jobs(
        [{"client": "Mansolino Sayra", "techs": []}], base, year=2026)
    assert len(rows) == 1
    assert rows[0]["folder"] == "Mansolino Sayra \\ 2nd Claim (KItchen)"


def test_reaudit_of_specific_claim_does_not_refan(tmp_path):
    # A row whose name already carries a claim suffix is a re-audit of ONE
    # claim — it must NOT fan back out to every claim.
    base = _setup(tmp_path, 2026, {
        "Mansolino Sayra": ["1st Claim", "2nd Claim (KItchen)"],
    })
    rows, _err = a.audit_jobs(
        [{"client": "Mansolino Sayra 2nd Claim (KItchen)", "techs": []}],
        base, year=2026)
    assert len(rows) == 1


# ── claim_number_from_hint — run-doc parenthetical → claim number ────

def test_claim_number_from_hint():
    assert a.claim_number_from_hint("1s claim") == 1      # common typo
    assert a.claim_number_from_hint("1st claim") == 1
    assert a.claim_number_from_hint("2nd claim Kitchen") == 2
    assert a.claim_number_from_hint("claim 2") == 2
    assert a.claim_number_from_hint("first claim") == 1
    assert a.claim_number_from_hint("second claim") == 2
    assert a.claim_number_from_hint("kitchen") is None    # no ordinal
    assert a.claim_number_from_hint("") is None


# ── Run-doc lines that already name the claim route 1:1, no fan-out ──

def test_runlines_with_claim_hints_route_each_to_its_subfolder(tmp_path):
    base = _setup(tmp_path, 2026, {
        "Mansolino Sayra": ["1st Claim", "2nd Claim (KItchen)"],
    })
    jobs = [
        {"client": "Sayra Mansolino", "claim_hint": "1s claim",
         "techs": [], "raw": "...(Mold After) ME"},
        {"client": "Sayra Mansolino", "claim_hint": "2nd claim Kitchen",
         "techs": [], "raw": "...(Mold After/Demo Thur 6/11) ME"},
    ]
    rows, _err = a.audit_jobs(jobs, base, year=2026)
    assert len(rows) == 2
    by_folder = {r["folder"]: r for r in rows}
    assert "Mansolino Sayra \\ 1st Claim" in by_folder
    assert "Mansolino Sayra \\ 2nd Claim (KItchen)" in by_folder
    # Distinct identities, both trace back to the bare run-doc name.
    assert {r["client"] for r in rows} == {
        "Sayra Mansolino 1st Claim",
        "Sayra Mansolino 2nd Claim (KItchen)",
    }
    assert all(r.get("claim_origin") == "Sayra Mansolino" for r in rows)


# ── Past-claim browsing: claim_folder_kind + list_claim_folders ─────

def test_claim_folder_kind_classifies():
    assert a.claim_folder_kind("1st Claim") == "claim"
    assert a.claim_folder_kind("2nd Claim (KItchen)") == "claim"
    assert a.claim_folder_kind("Claim 9-20-25") == "claim"
    assert a.claim_folder_kind("9-20-25") == "date"
    assert a.claim_folder_kind("09.20.2025") == "date"
    assert a.claim_folder_kind("2025-09-20") == "date"
    # Sub-assets and standard job folders are NOT claim folders.
    assert a.claim_folder_kind("Second Claim Photos") is None
    assert a.claim_folder_kind("EMS") is None
    assert a.claim_folder_kind("PICS") is None
    assert a.claim_folder_kind("Claim Photos") is None


def test_list_claim_folders_from_job_dir(tmp_path):
    job = tmp_path / "Mansolino Sayra"
    (job / "1st Claim").mkdir(parents=True)
    (job / "2nd Claim (Kitchen)").mkdir()
    (job / "9-20-25").mkdir()
    (job / "EMS").mkdir()  # not a claim folder
    folders = a.list_claim_folders(str(job))
    names = [f["name"] for f in folders]
    assert "EMS" not in names
    assert set(names) == {"1st Claim", "2nd Claim (Kitchen)", "9-20-25"}
    # Claim-numbered folders sort highest-first.
    assert names[0] == "2nd Claim (Kitchen)"


def test_list_claim_folders_surfaces_siblings_from_subfolder(tmp_path):
    job = tmp_path / "Mansolino Sayra"
    (job / "1st Claim").mkdir(parents=True)
    (job / "2nd Claim (Kitchen)").mkdir()
    # Called with a path that IS one claim subfolder — its siblings still
    # surface (parent is scanned), and itself is flagged current.
    folders = a.list_claim_folders(str(job / "2nd Claim (Kitchen)"))
    names = {f["name"] for f in folders}
    assert names == {"1st Claim", "2nd Claim (Kitchen)"}
    cur = [f for f in folders if f["is_current"]]
    assert len(cur) == 1 and cur[0]["name"] == "2nd Claim (Kitchen)"
