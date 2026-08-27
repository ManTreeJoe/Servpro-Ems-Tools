"""Email-aware job-log + EQ-lifecycle + job-lost detection.

Built from the real Club Pilates thread: a mostly-email Trello card where the
field notes ("Air scrubber picked up") carry their date only in the comment
timestamp, and a final "we moved ahead with another firm" email loses the job.
"""
import snapshot_logic as sg
import trello_client as tc


def _c(date, who, text):
    return {"date": date, "memberCreator": {"fullName": who},
            "data": {"text": text}}


# A representative subset of the real thread (ISO timestamps + authors).
COMMENTS = [
    _c("2026-06-13T19:51:00.000Z", "After Hours",
       "George received call. Address: Club Pilates 2785 Cabot Dr Corona. "
       "Reported damage involves a ceiling collapse with fiberglass insulation."),
    _c("2026-06-13T21:27:00.000Z", "Pablo Gonzalez",
       "INITIAL INSPECTION - FIELD TEMPLATE\nDate: 4:13\nMet With: Josie\n"
       "Equipment Placed: Yes\n1 Air Scrubber in Pilates room\n"
       "DocuSketch Completed: Yes"),
    _c("2026-06-16T20:54:00.000Z", "Pablo Gonzalez",
       "As of now, we are to put a pause until we hear back from Dan"),
    # A proposal email — has $ + 'option', must NOT create a 'Cleaning' event.
    _c("2026-06-24T15:35:00.000Z", "Pablo Gonzalez",
       "From: Pablo Gonzalez\nSent: Wednesday\nTo: Dan Danzig\nSubject: RE\n\n"
       "Hi Dan, Understood. We can revise the scope. HEPA vacuuming and "
       "detailed cleaning of the studio. Budget of approximately $5,500-$7,500."),
    _c("2026-06-18T20:12:00.000Z", "Samantha Gurganious",
       "this is placed on hold - please move to on hold on the run"),
    _c("2026-06-20T20:04:00.000Z", "Mark Escobar",
       "Air scrubber picked up. If any paperwork needs to be signed it will "
       "need to be emailed"),
    _c("2026-06-29T20:44:00.000Z", "Dan Danzig",
       "From: Dan Danzig\nSent: Monday\nTo: Pablo Gonzalez\nSubject: Re\n\n"
       "Hi Pablo, we moved ahead with another firm. Thank you for the follow up."),
]


def _by_activity(log):
    return {r["activity"]: r for r in log}


def test_job_log_core_events():
    log = sg.extract_job_log(COMMENTS)
    acts = _by_activity(log)
    assert "Initial Inspection" in acts
    assert acts["Initial Inspection"]["date"] == "6/13/26"
    assert acts["Initial Inspection"]["who"] == "PG"
    assert "EQ placed" in acts and acts["EQ placed"]["date"] == "6/13/26"
    assert "EQ picked up" in acts
    assert acts["EQ picked up"]["date"] == "6/20/26"
    assert acts["EQ picked up"]["who"] == "ME"
    assert "On hold" in acts
    assert "Job lost — went with another firm" in acts
    assert acts["Job lost — went with another firm"]["date"] == "6/29/26"


def test_proposal_email_does_not_fake_cleaning_visit():
    log = sg.extract_job_log(COMMENTS)
    assert "Cleaning" not in _by_activity(log)


def test_real_field_note_structures_are_recognized():
    comments = [
        _c("2026-08-14T18:00:00.000Z", "Field Supervisor",
           "Reinspection completed. Master bath drywall affected."),
        _c("2026-08-20T18:00:00.000Z", "Contents Technician",
           "Content Manipulation completed for this job. Boxes left in garage."),
        _c("2026-08-22T18:00:00.000Z", "Field Supervisor",
           "Job closed. Teardown completed. All plastic removed."),
        _c("2026-08-23T18:00:00.000Z", "Field Supervisor",
           "Stopped by and grabbed the EQ I stacked up on Saturday."),
        _c("2026-08-24T18:00:00.000Z", "Office Coordinator",
           "Kitchen containment passed the post fungal remediation criteria."),
    ]
    acts = _by_activity(sg.extract_job_log(comments))
    assert "Reinspection" in acts
    assert "Pack Out" in acts
    assert "Teardown" in acts
    assert "EQ picked up" in acts
    assert "Mold Clearance - Passed" in acts


def test_scheduled_requested_and_future_work_is_not_logged_as_completed():
    comments = [
        _c("2026-08-14T18:00:00.000Z", "Coordinator",
           "Re-inspection scheduled for tomorrow between 1-3pm."),
        _c("2026-08-15T18:00:00.000Z", "Coordinator",
           "Please dispatch mold clearance. This will be ready by Saturday."),
        _c("2026-08-16T18:00:00.000Z", "Coordinator",
           "Pack out approval pending management review."),
        _c("2026-08-17T18:00:00.000Z", "Coordinator",
           "Demo approved to proceed next week."),
    ]
    assert sg.extract_job_log(comments) == []


def test_completed_and_future_events_in_same_comment_stay_separate():
    log = sg.extract_job_log([_c(
        "2026-08-20T18:00:00.000Z", "Field Supervisor",
        "Demo completed today. Monitor scheduled tomorrow morning.")])
    acts = _by_activity(log)
    assert "Demo" in acts
    assert "Monitor" not in acts


def test_office_posters_keep_event_but_are_not_listed_as_techs():
    for office_name in ("Laura Barajas", "Victoria Robledo",
                        "Samantha Gurganious", "Sam Coordinator"):
        rows = sg.extract_job_log([_c(
            "2026-08-20T18:00:00.000Z", office_name,
            "Demo completed today.")])
        assert rows[0]["activity"] == "Demo"
        assert rows[0]["who"] == ""


def test_office_report_uses_technician_named_in_comment_body():
    rows = sg.extract_job_log([_c(
        "2026-08-20T18:00:00.000Z", "Laura Barajas",
        "Initial Inspection performed by Supervisor Fernando Baca.")])
    assert rows[0]["activity"] == "Initial Inspection"
    assert rows[0]["who"] == "FB"


def test_job_log_sorted_oldest_first():
    log = sg.extract_job_log(COMMENTS)
    dates = [r["date"] for r in log]
    assert dates == sorted(dates, key=lambda d: tuple(
        int(x) for x in (d.split("/")[2], d.split("/")[0], d.split("/")[1])))


def test_eq_lifecycle_placed_then_picked_up():
    eq = sg.eq_lifecycle(COMMENTS)
    assert eq["placed"] == ["6/13/26"]
    assert eq["picked_up"] == ["6/20/26"]
    assert eq["outstanding"] is False


def test_eq_lifecycle_flags_outstanding_equipment():
    # Drop the pickup note → equipment still on site.
    no_pickup = [c for c in COMMENTS if "picked up" not in c["data"]["text"]]
    eq = sg.eq_lifecycle(no_pickup)
    assert eq["outstanding"] is True
    assert eq["days_out"] is not None and eq["days_out"] >= 1


def test_job_lost_phrase_routes_to_incomplete(monkeypatch):
    monkeypatch.setattr(tc, "get_logs_board_id", lambda: "LOGSBOARD")
    monkeypatch.setattr(tc, "get_ar_board_id", lambda: "ARBOARD")
    # A would-be-Completed (LOGS board) closed card whose comments say the
    # customer went elsewhere must route to Incomplete, not Completed.
    card = {"idBoard": "LOGSBOARD", "closed": True, "labels": []}
    status = tc.card_route_status(
        card, comments_text="we moved ahead with another firm")
    assert status == "incomplete"
