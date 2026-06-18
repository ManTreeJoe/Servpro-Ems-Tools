"""Add-to-APA dialog section list. PENDING REVIEW (a normal, non-
estimator section) must be offered so a card in the estimating board's
'Pending Review' lane can be filed there.
"""
import apa_web


def test_pending_review_is_offered_in_add_dialog():
    names = [d["name"] for d in apa_web.Api().add_dialog_sections()]
    assert "PENDING REVIEW" in names


def test_pending_review_sub_is_estimator():
    # Pending Review uses the ESTIMATOR as its sub, just like the
    # Audit Rejection/Dispute rows — so the dialog shows a Sub dropdown.
    rows = {d["name"]: d for d in apa_web.Api().add_dialog_sections()}
    assert rows["PENDING REVIEW"]["has_subs"] is True

    import apa_logic
    subs = apa_web.Api().status_options("PENDING REVIEW").get("subs")
    assert subs == [""] + list(apa_logic.ESTIMATORS_ORDERED)
