"""reaudit_one (snapshot + single-card audit) claim-folder resolution.

A claim-suffixed client name audited directly makes the folder lookup
descend to the LATEST claim folder (the snapshot audit then showed the
WRONG claim). reaudit_one now strips the claim label to the base, expands
per claim, and picks the matching row. This locks the claim-label parsing
+ base-strip that resolution depends on (the same `claim_label_from_folder`
the fix calls).
"""
import audit_logic as al


def _base_of(client):
    """Mirror the base-strip reaudit_one does before expanding."""
    lbl = al.claim_label_from_folder(client)
    if not lbl:
        return client, ""
    idx = client.lower().rfind(lbl.lower())
    base = client[:idx].strip() if idx > 0 else client
    return base or client, lbl


def test_claim_label_and_base_split():
    base, lbl = _base_of("Mansolino Sayra 1st Claim")
    assert lbl == "1st Claim"
    assert base == "Mansolino Sayra"


def test_claim_label_keeps_parenthetical_descriptor():
    base, lbl = _base_of("Mansolino Sayra 2nd Claim (KItchen)")
    assert lbl == "2nd Claim (KItchen)"
    assert base == "Mansolino Sayra"


def test_non_claim_name_unchanged():
    base, lbl = _base_of("Smith John")
    assert lbl == ""
    assert base == "Smith John"


def test_matching_picks_right_claim_from_expanded_results():
    # Given expanded per-claim results, the exact-client match wins —
    # the same selection reaudit_one does.
    results = [
        {"client": "Mansolino Sayra 1st Claim",
         "path": r"X:\J\Mansolino Sayra\1st Claim"},
        {"client": "Mansolino Sayra 2nd Claim (KItchen)",
         "path": r"X:\J\Mansolino Sayra\2nd Claim (KItchen)"},
    ]
    target = "Mansolino Sayra 1st Claim"

    def _cn(s):
        return " ".join((s or "").strip().lower().split())
    chosen = next((r for r in results if _cn(r["client"]) == _cn(target)), None)
    assert chosen is not None
    assert chosen["path"].endswith(r"1st Claim")     # NOT the 2nd-claim folder
