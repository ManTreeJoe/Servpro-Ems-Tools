"""parse_xa_notification — pulls Insured / Claim # / Note from the
templated `donotreply@xactware.com` notification emails.

Regression guard for the 2026-06-10 truncation bug: the note body opens
with a greeting on its own line ("Good Morning,\\r\\n\\r\\n<real text>")
and Verisk uses Windows CRLF line endings. The old regex terminated on
`$` under re.MULTILINE, so the capture stopped at the end of the FIRST
line — the actual adjuster question after the greeting was silently
dropped. These tests pin the full multi-line capture across CRLF.
"""
import xa_email_ingest as xa


def _body(note_block, *, insured="GEORGE PETERSEN", claim="017877069"):
    # Build with real Windows CRLF endings — the bug only reproduced with \r\n.
    lines = [
        "An assignment note was added in XactAnalysis.",
        "",
        f"Insured: {insured}",
        f"Claim #: {claim}",
        "Note:",
        note_block,
        "",
        "To view the detailed information click on the following link",
        "https://www.xactanalysis.com/...",
    ]
    return "\r\n".join(lines)


def test_insured_and_claim_extracted():
    body = _body("Hello, please proceed.")
    f = xa.parse_xa_notification("An Assignment Note Has Been Added", body)
    assert f["insured"] == "GEORGE PETERSEN"
    assert f["claim"] == "017877069"


def test_multiline_note_not_truncated_to_greeting():
    note = ("Good Morning,\r\n\r\n"
            "Is any mitigation actually needed since it's just wet "
            "flooring?\r\n\r\n"
            "Also are you able to handle the repair portion?")
    body = _body(note)
    f = xa.parse_xa_notification("...", body)
    # The greeting alone must NOT be the whole capture.
    assert f["note"].strip() != "Good Morning,"
    assert "mitigation actually needed" in f["note"]
    assert "repair portion" in f["note"]


def test_footer_stripped_from_note():
    body = _body("Good afternoon,\r\n\r\nWill this 5k limit be exceeded?")
    f = xa.parse_xa_notification("...", body)
    assert "To view the detailed information" not in f["note"]
    assert "Will this 5k limit be exceeded?" in f["note"]


def test_single_line_note_still_works():
    body = _body("please upload diving board sub bid asap.")
    f = xa.parse_xa_notification("...", body)
    assert f["note"].strip() == "please upload diving board sub bid asap."


def test_insured_falls_back_to_subject():
    body = "Note:\r\nSome note text here\r\n"
    f = xa.parse_xa_notification(
        "An Assignment Note Has Been Added in XactAnalysis Insured: CAMP, JOHN",
        body)
    assert f["insured"] == "CAMP, JOHN"
