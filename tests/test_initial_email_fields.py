"""Arrival time + date come from the tech's initial note; no franchise line.

On live cards the arrival Time came through empty on every one, because
the draft joined EVERY comment into a single string and took the first
block out of it. Comments arrive newest-first, so an unrelated later
comment that tripped the label heuristic beat the actual report — and
joining across comment boundaries could form a block nobody wrote.
"""

import audit_logic
import initial_email as ie
import initial_notes_parser as inp


REPORT = """PRELIMINARY INSPECTION REPORT & BUDGETARY ESTIMATE
Date of Inspection: 04/18/2026
Time: 12:15 PM
Cause of Loss:
Supply line failure under the sink.
"""

TEMPLATE = """Initial Inspection
Date: 6-10-26
Time of Inspection: 1:00 pm
Met With: Owner
Cause of Loss: Water heater
Category: 2
"""

CHATTER = "Met with hvac guy. He will send over an estimate.\n@george10100"


# ── picking the right block ─────────────────────────────────────────

def test_the_report_heading_is_recognised():
    # Without this the block was only found by the count-the-labels
    # fallback, which needs four labels in one comment — these reports
    # carry three and then prose.
    got = inp.parse_initial_inspection_notes(REPORT)
    assert got and got[0].get("Time") == "12:15 PM"
    assert got[0].get("Date") == "04/18/2026"


def test_a_bold_heading_still_matches():
    got = inp.parse_initial_inspection_notes(
        REPORT.replace("PRELIMINARY INSPECTION REPORT & BUDGETARY ESTIMATE",
                       "**PRELIMINARY INSPECTION REPORT**"))
    assert got and got[0].get("Time") == "12:15 PM"


def test_chatter_does_not_beat_the_real_report():
    # Newest-first is the order comments actually arrive in.
    best = inp.best_initial_block([CHATTER, REPORT])
    assert best.get("Time") == "12:15 PM"


def test_the_block_with_an_arrival_time_wins():
    no_time = TEMPLATE.replace("Time of Inspection: 1:00 pm\n", "")
    best = inp.best_initial_block([no_time, TEMPLATE])
    assert best.get("Time") == "1:00 pm"


def test_comments_are_never_joined_into_one_block():
    # The tail of one comment and the head of the next must not combine.
    half_a = "Initial Inspection\nDate: 6-10-26\n"
    half_b = "Time of Inspection: 9:99 pm\nMet With: nobody\n"
    best = inp.best_initial_block([half_a, half_b])
    assert best.get("Time") != "9:99 pm"


def test_nothing_parseable_returns_empty():
    assert inp.best_initial_block([CHATTER]) == {}
    assert inp.best_initial_block([]) == {}
    assert inp.best_initial_block(["", None]) == {}


def test_a_typo_is_passed_through_not_corrected():
    # A real card says "7::30am". Inventing a time would be worse.
    txt = TEMPLATE.replace("1:00 pm", "7::30am")
    assert inp.best_initial_block([txt]).get("Time") == "7::30am"


# ── the email itself ────────────────────────────────────────────────

def test_no_franchise_line():
    out = ie.compose({"Date": "6-10-26", "Time": "1:00 pm"},
                     franchise="L&P Group, Inc. d/b/a SERVPRO of Woodcrest",
                     supervisor="Fernando")
    assert "L&P Group" not in out
    assert "[FRANCHISE]" not in out


def test_the_email_opens_with_the_greeting():
    out = ie.compose({}, greeting="Good Morning,")
    assert out.splitlines()[0] == "Good Morning,"


def test_arrival_time_and_date_reach_the_email():
    out = ie.compose({"Date": "04/18/2026", "Time": "12:15 PM"},
                     supervisor="Fernando")
    assert "12:15 PM" in out
    assert "[ARRIVAL TIME]" not in out
    assert "[DATE]" not in out


# ── supervisors are tech leads ──────────────────────────────────────

def test_every_named_lead_is_recognised():
    for lead in ("Fernando", "Rudy", "Pablo", "Mark E", "Mark L",
                 "Aaron", "Johnny"):
        assert audit_logic.is_tech_lead(lead), lead


def test_a_lead_is_recognised_by_initials_and_full_name():
    assert audit_logic.is_tech_lead("FB")
    assert audit_logic.is_tech_lead("fernando baca")
    assert audit_logic.is_tech_lead("ME")


def test_a_crew_member_is_not_a_lead():
    for who in ("Wendy", "Priscilla", "Vince", "Brenda", ""):
        assert not audit_logic.is_tech_lead(who), who
