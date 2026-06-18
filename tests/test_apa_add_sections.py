"""Add-to-APA dialog section list. PENDING REVIEW (a normal, non-
estimator section) must be offered so a card in the estimating board's
'Pending Review' lane can be filed there.
"""
import apa_web


def test_pending_review_is_offered_in_add_dialog():
    names = [d["name"] for d in apa_web.Api().add_dialog_sections()]
    assert "PENDING REVIEW" in names


def test_pending_review_has_no_sub_dropdown():
    rows = {d["name"]: d for d in apa_web.Api().add_dialog_sections()}
    # Like estimators / Estimating-* — no Sub dropdown for Pending Review.
    assert rows["PENDING REVIEW"]["has_subs"] is False
