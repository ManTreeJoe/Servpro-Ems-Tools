"""Multi-claim jobs must produce DISTINCT rows (audit_web).

Sayra Mansolino has two independent claims under one job name (1st Claim /
2nd Claim (Kitchen)). The daily run's one run-doc line expands into two
audit results. Each must shape into its OWN row with a distinct
client + row_key so the frontend selects / pins / folders them
independently — selecting or pinning one must NOT touch the other.

Bug (2026-06-23): the daily-run shaping adopted the result's per-row
client ONLY when `r.get("subjob")` was True. Multi-claim rows are NOT
flagged subjob, so both claims kept the BASE run-doc client + row_key
and collapsed into one selectable row.
"""
import audit_web as aw


def _shape_pair(jobs, results):
    """Re-implements the daily-run pairing+override+shape so the test
    locks the exact behavior without spinning up the audit core."""
    rows = []
    for j, r in aw._pair_results_to_jobs(jobs, results):
        r = r or {}
        _rc = r.get("client") or ""
        if _rc and _rc != (j or {}).get("client"):
            j = {**(j or {}), "client": _rc}
            if r.get("subjob"):
                j["subjob"] = True
        rows.append(aw._shape_job(j, r, ""))
    return rows


def test_multiclaim_rows_have_distinct_keys():
    jobs = [{"client": "Mansolino Sayra", "section": "work",
             "raw": "", "techs": []}]
    results = [
        {"client": "Mansolino Sayra 1st Claim",
         "claim_origin": "Mansolino Sayra",
         "path": r"X:\Jobs\Mansolino Sayra\1st Claim",
         "found": True, "form_issues": [], "photo_issues": [],
         "note_issues": [], "aging": 0, "flagged": False},
        {"client": "Mansolino Sayra 2nd Claim (Kitchen)",
         "claim_origin": "Mansolino Sayra",
         "path": r"X:\Jobs\Mansolino Sayra\2nd Claim (Kitchen)",
         "found": True, "form_issues": [], "photo_issues": [],
         "note_issues": [], "aging": 0, "flagged": False},
    ]
    rows = _shape_pair(jobs, results)
    assert len(rows) == 2
    clients = {r["client"] for r in rows}
    keys = [r["row_key"] for r in rows]
    # Each claim keeps its own identity — NOT collapsed to "Mansolino Sayra".
    assert clients == {"Mansolino Sayra 1st Claim",
                       "Mansolino Sayra 2nd Claim (Kitchen)"}
    assert len(set(keys)) == 2                 # distinct row_keys
    assert "Mansolino Sayra" not in keys       # base name never used as a key
    # Distinct paths preserved per claim.
    assert len({r["path"] for r in rows}) == 2


def test_normal_job_unaffected():
    # A normal job (result client == run-doc client) shapes one row keyed
    # by that client — the override must not alter it.
    jobs = [{"client": "Smith John", "section": "work", "raw": "", "techs": []}]
    results = [{"client": "Smith John", "path": r"X:\Jobs\Smith John",
                "found": True, "form_issues": [], "photo_issues": [],
                "note_issues": [], "aging": 0, "flagged": False}]
    rows = _shape_pair(jobs, results)
    assert len(rows) == 1
    assert rows[0]["client"] == "Smith John"
    assert rows[0]["row_key"] == "Smith John"
