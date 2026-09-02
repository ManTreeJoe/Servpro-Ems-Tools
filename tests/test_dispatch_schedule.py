from datetime import date

from dispatch_schedule import DispatchSchedule


class FakeRunDocs:
    def read(self, day):
        if day != date(2026, 9, 2):
            return {"exists": False, "editable": False, "jobs": []}
        return {
            "exists": True,
            "editable": True,
            "jobs": [
                {
                    "client": "Jasmin Rose",
                    "techs": ["Marco C", "Jose E"],
                    "time_slot": "8-10 AM",
                    "section": "monitor",
                    "raw": "Rose, Jasmin - Monitor - MC / JE - 8-10 AM",
                },
                {
                    "client": "Unlinked Customer",
                    "techs": ["Marco C"],
                    "section": "work",
                    "raw": "Unlinked Customer - MC",
                },
            ],
        }


def schedule():
    return DispatchSchedule(
        reader=FakeRunDocs(),
        tech_email_provider=lambda: {
            "Marco C": "marco@servpro.example",
            "Jose E": "jose@servpro.example",
        },
    )


def test_run_doc_is_source_and_unlinked_lines_remain_visible():
    result = schedule().load([{
        "card_id": "card-1", "job_id": "job-1",
        "client": "Rose, Jasmin", "lane": "ACTIVE", "division": "EMS",
    }], start=date(2026, 9, 2), days=2)
    today = result["days"][0]
    assert result["source"] == "run_doc"
    assert today["exists"] is True and today["editable"] is True
    assert today["jobs"][0]["card_id"] == "card-1"
    assert today["jobs"][0]["time_slot"] == "8-10 AM"
    assert today["jobs"][1]["matched"] is False
    assert today["jobs"][1]["client"] == "Unlinked Customer"


def test_employee_dispatch_uses_server_owned_email_or_display_name_mapping():
    full = schedule().load([], start=date(2026, 9, 2), days=1)
    marco = schedule().for_user(full, email="MARCO@servpro.example")
    jose = schedule().for_user(full, display_name="Jose E")
    assert [item["client"] for item in marco["days"][0]["jobs"]] == [
        "Jasmin Rose", "Unlinked Customer"]
    assert [item["client"] for item in jose["days"][0]["jobs"]] == [
        "Jasmin Rose"]
    assert marco["unscheduled_count"] == 0


def test_employee_full_name_matches_run_doc_roster_abbreviation():
    full = {
        "days": [{"date": "2026-09-02", "jobs": [{
            "client": "A Job", "technicians": ["Mark E"],
            "technician_emails": [],
        }]}],
        "unscheduled": [], "unscheduled_count": 0,
    }
    result = schedule().for_user(full, display_name="Mark Escobar")
    assert len(result["days"][0]["jobs"]) == 1


def test_active_jobs_absent_from_run_docs_stay_in_unscheduled_tray():
    jobs = [
        {"card_id": "scheduled", "client": "Rose, Jasmin"},
        {"card_id": "waiting", "client": "Waiting, Client"},
    ]
    result = schedule().load(jobs, start=date(2026, 9, 2), days=1)
    assert result["unscheduled_count"] == 1
    assert result["unscheduled"][0]["card_id"] == "waiting"
