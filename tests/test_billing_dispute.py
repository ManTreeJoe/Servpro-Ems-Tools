"""Billing-dispute email parser → dispute payload."""
from dispute_email_scan import parse_billing_dispute

EMAIL = """Billing Dispute Opened, ATTENTION NEEDED!!!

Line 4 please adjust to DMO DUMP as it is more appropriate (Net Reduction $751.05)
Line 7 please adjust to WTR FCWN as bagging not documented (Net Reduction $1,537.34)
Line 18 please adjust to 5 day per noted approval (Net Reduction $564.00)

Total adjustments of $6,899.45 to original invoice amount of $35,990.84 resulting in revised total of $29,091.39"""


def test_parses_lines_and_totals():
    p = parse_billing_dispute(EMAIL)
    assert p is not None
    assert len(p["lines"]) == 3
    assert p["lines"][0] == {"line": 4,
                             "reason": "DMO DUMP as it is more appropriate",
                             "reduction": 751.05}
    assert p["totals"] == {"adjustments": 6899.45,
                           "original": 35990.84, "revised": 29091.39}


def test_amount_is_total_adjustments():
    assert parse_billing_dispute(EMAIL)["amount"] == "6,899.45"


def test_amount_falls_back_to_line_sum():
    # No totals line → amount is the sum of the per-line reductions.
    txt = ("Line 1 adjust A (Net Reduction $100.00)\n"
           "Line 2 adjust B (Net Reduction $50.50)")
    assert parse_billing_dispute(txt)["amount"] == "150.50"


def test_summary_lists_lines_and_totals():
    s = parse_billing_dispute(EMAIL)["summary"]
    assert "Line 4:" in s and "Revised total: $29,091.39" in s


def test_non_dispute_returns_none():
    assert parse_billing_dispute("Hi, following up on the estimate. Thanks.") is None
    assert parse_billing_dispute("") is None
