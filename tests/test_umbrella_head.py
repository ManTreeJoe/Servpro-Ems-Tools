"""Commercial-parent umbrella head = container, not a job.

The head (e.g. "Menifee School District") must not get an SP scan; its
sub-jobs (campuses) do. Locks the enrich_with_sharepoint short-circuit.
"""
import sp_enrich


def test_sp_enrichment_skips_umbrella_head():
    r = {"client": "Menifee School District", "is_parent": True,
         "path": r"X:\IE_Public\2026 Jobs\Menifee Union School District"}
    sp_enrich.enrich_with_sharepoint(r, "06-17-2026")
    # No SP scan ran — counters stay clean, no matches.
    assert r.get("sharepoint_matches") == []
    assert r.get("sharepoint_new") == 0
    # And it didn't populate pics options (the scan body was skipped).
    assert "pics_options" not in r
