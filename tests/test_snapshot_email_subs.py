"""Sub-contractor extraction from email blocks in snapshot parsing.

The line-by-line parser drops `From:` / `Subject:` / `We have...` lines
via `email_skip`, so subs whose only signal is on those lines (e.g.
Safeguard EnviroGroup mold clearance emails) used to vanish.

`_extract_email_block_subs` reads each email block holistically, looking
across the From line, body, and Sent header for sub identity, activity,
and date — including long-form dates like "April 29, 2026".

Pinning the two real examples that surfaced this bug here so the
behavior can't drift quietly."""
import snapshot_gui


SAFEGUARD_TESTING = """\
From: Client Services (Safeguard EnviroGroup) <clientservices@safeguardenviro.com>
Sent: Monday, April 27, 2026 9:14 AM
Subject: Confirmed - Mold Clearance Testing 4/29

Hello,

We have confirmed testing for 4/29 at the Smith property.

Sincerely,
Client Services
"""

SAFEGUARD_PASSED = """\
From: Safeguard EnviroGroup (Client Services) <clientservices@safeguardenviro.com>
Sent: Wednesday, April 29, 2026 5:53 PM
Subject: Clearance Results

Sample results PASSED our clearance criteria.

Sincerely,
Client Services
"""


def test_safeguard_testing_email_yields_sub_row():
    sub_rows, _ = snapshot_gui.parse_comments(SAFEGUARD_TESTING)
    safeguard = [r for r in sub_rows if r[3] == "Safeguard"]
    assert safeguard, f"Expected Safeguard row, got {sub_rows}"
    date, _wd, activity, _sub = safeguard[0]
    assert date == "4/29/26"
    assert "Mold Clearance Testing" in activity


def test_safeguard_passed_email_uses_long_form_date():
    """No slash date in the body — only "April 29, 2026" in the Sent
    header. The long-form fallback must catch it."""
    sub_rows, _ = snapshot_gui.parse_comments(SAFEGUARD_PASSED)
    safeguard = [r for r in sub_rows if r[3] == "Safeguard"]
    assert safeguard, f"Expected Safeguard row, got {sub_rows}"
    date, _wd, activity, _sub = safeguard[0]
    assert date == "4/29/26"
    assert activity == "Mold Clearance - Passed"


def test_dispatch_lines_still_parsed_when_email_appended():
    """Email-block extraction must not displace the line-by-line loop —
    a regular dispatch line above an email still produces its log row."""
    raw = "Demo 4/28/26 with Vince and Pablo\n\n" + SAFEGUARD_TESTING
    sub_rows, log_rows = snapshot_gui.parse_comments(raw)
    assert any("Demo" in r[2] for r in log_rows), \
        f"Demo dispatch line lost; log_rows={log_rows}"
    assert any(r[3] == "Safeguard" for r in sub_rows)


def test_no_email_block_returns_no_extras():
    """Plain dispatch text with no From: line shouldn't synthesize subs."""
    sub_rows, _ = snapshot_gui.parse_comments(
        "Demo 4/28/26 with Vince\nMold prep 4/29/26 with Pablo")
    assert not [r for r in sub_rows if r[3] == "Safeguard"]


def test_duplicate_emails_dont_duplicate_sub_rows():
    """Same Safeguard email appearing twice in a paste must not double the row."""
    sub_rows, _ = snapshot_gui.parse_comments(
        SAFEGUARD_PASSED + "\n\n" + SAFEGUARD_PASSED)
    safeguard = [r for r in sub_rows if r[3] == "Safeguard"]
    assert len(safeguard) == 1


def test_mark_l_detected_in_dispatch_line():
    """Pin the shared TECH_PATTERN reuse — 'Mark L' was previously
    dropped because snapshot_gui's local pattern only knew 'Mark E'."""
    _, log_rows = snapshot_gui.parse_comments("Demo - Danny/Mark L 1st 4/29/26")
    assert log_rows, "Demo line not parsed"
    techs = log_rows[0][3]
    assert "Danny" in techs
    assert "Mark L" in techs
