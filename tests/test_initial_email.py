"""The Initial Inspection email drafted from the card's own notes.

The office retypes this for every new job. Almost all of it is already
in the tech's initial-inspection notes, so it gets composed from them.

The wording is the user's, verbatim, and is asserted here as such: an
adjuster who reads "Re-inspection is recommended upon completion of
repairs" on twenty claims must read the same sentence on the twenty-
first, so these are fixed strings, not generated prose.
"""
import pytest

import initial_email as ie

# The tech's notes behind the user's real example.
FIELDS = {
    "Date": "6/29/26", "Time": "4:00PM", "Met With": "Insured",
    "Cause of Loss": "Master toilet supply line", "Category": "2",
    "Plumbing Repairs": "No", "Re-inspection": "Yes",
    "Levels Affected": "1",
    "Downstairs": ("Master Bathroom - Ceiling/Vanity/Walls; "
                   "Master Bedroom - Walls/Carpet/Pad; Living Room - Walls"),
    "Asbestos/Lead Test": "Yes", "Packout Required": "Yes",
    "Storage Type": "POD", "Equipment Placed": "Yes",
    "Video Taken": "https://share.vidyard.com/watch/abc123",
}

OPTS = dict(franchise="Servpro of Woodcrest/Lake Matthews/El Ce",
            supervisor="Mark Escobar", year_built="1949",
            equipment_rate="$85.26", crews_date="6/30/26",
            extras={"services": ["CLN of the affected areas",
                                 "Application of Anti-microbial to the "
                                 "affected areas"]})


@pytest.fixture(scope="module")
def draft():
    return ie.compose(FIELDS, **OPTS)


# ── the sentences, verbatim ────────────────────────────────────────────
@pytest.mark.parametrize("line", [
    "Good Morning,",
    "Initial Inspection performed Monday 6/29/26 Supervisor Mark Escobar",
    "Arrival Time:4:00PM",
    "Met With: Insured",
    "COL: Master toilet supply line",
    "CAT: 2",
    "Repairs have yet to be completed",
    "Re-inspection is recommended upon completion of repairs",
    "Areas affected:",
    "Number of Levels Affected: 1",
    "Property built in 1949",
    "Asbestos and Lead testing is required",
    "Pack out will be necessary to facilitate mitigation",
    "Packing materials will be utilized",
    "The time allotted per room under the SLA will be exceeded",
    "POD is required",
    "TL inventory is required",
    "Equipment placed to stabilize environment",
    "Three-day dry time will be exceeded",
    "Please note, equipment onsite is incurring costs at $85.26 per day",
    "CLN of the affected areas",
    "Please note, ESL will be exceeded",
    "Crews en route to commence mitigation Tuesday, 6/30/26",
    "Regards,",
])
def test_expected_line_is_present(draft, line):
    assert line in draft


def test_the_franchise_is_not_named(draft):
    """The email goes out from a mailbox that already identifies the
    office (user, 2026-08-12). It used to lead with the franchise, which
    also meant a literal "[FRANCHISE]" reached adjusters whenever it
    wasn't configured. `franchise` is still accepted, just not printed."""
    assert "Servpro of Woodcrest" not in draft
    assert "[FRANCHISE]" not in draft
    assert draft.splitlines()[0].startswith("Good")


def test_rooms_are_listed_one_per_line(draft):
    assert "Master Bathroom - Ceiling/Vanity/Walls" in draft
    assert "Master Bedroom - Walls/Carpet/Pad" in draft
    assert "Living Room - Walls" in draft


def test_walkthrough_link_and_its_preamble(draft):
    assert ("Please copy & paste the link below into your preferred "
            "browser to view initial walkthrough:") in draft
    assert "https://share.vidyard.com/watch/abc123" in draft


def test_nothing_left_bracketed_when_notes_are_complete(draft):
    assert ie.missing_placeholders(draft) == []


# ── dates ──────────────────────────────────────────────────────────────
def test_weekday_is_derived():
    assert ie.format_inspection_date("6/29/26") == "Monday 6/29/26"


def test_crews_line_takes_a_comma():
    """The office punctuates that one line differently."""
    assert ie.format_inspection_date("6/30/26", comma=True) == "Tuesday, 6/30/26"


def test_existing_weekday_is_not_doubled():
    assert ie.format_inspection_date("Monday 6/29/26") == "Monday 6/29/26"


def test_unparseable_date_is_left_alone():
    """Never invent a date on a claim document."""
    assert ie.format_inspection_date("next week") == "next week"
    assert ie.format_inspection_date("13/45/99") == "13/45/99"


# ── yes/no handling ────────────────────────────────────────────────────
def test_completed_repairs_flip_the_sentence():
    out = ie.compose(dict(FIELDS, **{"Plumbing Repairs": "Yes"}), **OPTS)
    assert "Repairs have been completed" in out
    assert "Repairs have yet to be completed" not in out


def test_half_struck_answers_are_read():
    """Techs leave "Yes /" and "/ No" behind when they strike one out."""
    assert ie._tri("Yes /") is True
    assert ie._tri("/ No") is False
    assert ie._tri("Yes / No") is None      # unanswered
    assert ie._tri("") is None


def test_no_testing_drops_the_testing_line():
    out = ie.compose(dict(FIELDS, **{"Asbestos/Lead Test": "No"}), **OPTS)
    assert "Asbestos and Lead testing is required" not in out


def test_no_packout_drops_the_whole_packout_block():
    out = ie.compose(dict(FIELDS, **{"Packout Required": "No"}), **OPTS)
    for line in ("Pack out will be necessary", "Packing materials",
                 "SLA will be exceeded", "POD is required",
                 "TL inventory is required"):
        assert line not in out


def test_operator_override_beats_the_notes():
    """The dialog's checkboxes assert what the notes left blank."""
    out = ie.compose(dict(FIELDS, **{"Asbestos/Lead Test": ""}),
                     **dict(OPTS, extras={"testing": True}))
    assert "Asbestos and Lead testing is required" in out


# ── gaps are visible, never guessed ────────────────────────────────────
def test_missing_fields_become_visible_placeholders():
    out = ie.compose({}, franchise="X", supervisor="Y")
    miss = ie.missing_placeholders(out)
    assert "[DATE]" in miss and "[ARRIVAL TIME]" in miss
    assert "[CAUSE OF LOSS]" in miss and "[CAT]" in miss
    assert "[AFFECTED AREAS]" in miss


def test_no_equipment_rate_is_bracketed_not_blank():
    out = ie.compose(FIELDS, **dict(OPTS, equipment_rate=""))
    assert "[$/DAY]" in out


def test_no_services_drops_the_services_preamble():
    out = ie.compose(FIELDS, **dict(OPTS, extras={}))
    assert "the following services are going to be performed" not in out


def test_blank_walkthrough_drops_its_preamble():
    out = ie.compose(dict(FIELDS, **{"Video Taken": ""}),
                     **dict(OPTS, walkthrough_url=""))
    assert "view initial walkthrough" not in out


def test_no_runaway_blank_lines(draft):
    assert "\n\n\n" not in draft


# ── the endpoints ──────────────────────────────────────────────────────
def test_comment_body_is_the_office_phrasing(monkeypatch):
    import audit_web
    import trello_client as tc
    sent = {}
    monkeypatch.setattr(tc, "post_comment",
                        lambda cid, text: sent.update(card=cid, text=text))

    class _Api(audit_web.Api):
        def __init__(self):
            pass
    res = _Api().post_initial_email_comment("card1", "XactAnalysis")
    assert res["ok"]
    assert sent["text"] == "Initial Inspection email sent to XactAnalysis / XactAnalysis"


def test_comment_needs_a_card():
    import audit_web

    class _Api(audit_web.Api):
        def __init__(self):
            pass
    assert _Api().post_initial_email_comment("")["ok"] is False


def test_snapshot_proxies_the_initial_email_api():
    """audit_detail.js is ONE card rendered by audit AND snapshot."""
    import snapshot_web
    for name in ("initial_email_draft", "compose_initial_email",
                 "post_initial_email_comment", "open_xa_link"):
        assert hasattr(snapshot_web.Api, name), f"snapshot_web missing {name}"
