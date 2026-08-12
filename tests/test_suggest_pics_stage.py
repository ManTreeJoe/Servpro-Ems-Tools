"""Suggest a PICS stage for untagged CompanyCam photos, from the run doc.

CompanyCam routes photos by their own tags, but plenty arrive untagged —
and then someone has to remember what that visit was, days later, for a
job they may not have been on. The run doc recorded it at the time.

A wrong guess files photos where nobody looks for them, so "no idea" has
to stay expressible.
"""

import datetime as dt

import pytest

import run_doc


@pytest.fixture
def day(monkeypatch):
    """Point the lookup at a fake run doc we control."""
    jobs = []

    def _set(*rows):
        jobs.clear()
        jobs.extend(rows)

    monkeypatch.setattr(run_doc, "_find_run_doc_for_date",
                        lambda d: "fake.docx")

    class _Hub:
        def parse_run_doc(self, path):
            return list(jobs), "08-11-2026"

    import state_hub
    monkeypatch.setattr(state_hub, "hub", _Hub())
    return _set


def _job(client, raw, section="work", new_loss=False):
    return {"client": client, "raw": raw, "section": section,
            "new_loss": new_loss}


# ── the activities that map to a real folder ────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("Smith: 1 Main St (Demo) FB",              "Demo"),
    ("Smith: 1 Main St (Mold Prep) FB",         "Mold Prep"),
    ("Smith: 1 Main St (Reinspection) FB",      "Reinspection"),
    ("Smith: 1 Main St (Initial Inspection) FB", "Initial"),
    ("Smith: 1 Main St (Teardown) FB",          "Post"),
])
def test_the_run_line_picks_the_stage(day, raw, expect):
    day(_job("Smith", raw))
    assert run_doc.suggest_pics_stage("08-11-2026", "Smith") == expect


def test_a_monitor_visit_suggests_monitor(day):
    # Monitor needs no photos so carries no "expected" folder — but a
    # monitor visit that DID produce photos still belongs under Monitor.
    day(_job("Smith", "Smith: 1 Main St (Monitor) FB", section="monitor"))
    assert run_doc.suggest_pics_stage("08-11-2026", "Smith") == "Monitor"


def test_a_new_loss_suggests_initial(day):
    day(_job("Smith", "Smith: 1 Main St FB", new_loss=True))
    assert run_doc.suggest_pics_stage("08-11-2026", "Smith") == "Initial"


# ── declining is a valid answer ─────────────────────────────────────

def test_a_packout_suggests_nothing(day):
    # Real line from 08-11. Pack-out expects Contents, which is a separate
    # scope, not a PICS stage — there is no right folder to offer.
    day(_job("Edward Ochoa",
             "Edward Ochoa: 4904 Prairie Run Rd (Packout) Brenda/Wendy"))
    assert run_doc.suggest_pics_stage("08-11-2026", "Edward Ochoa") == ""


def test_an_unrecognised_activity_suggests_nothing(day):
    day(_job("David Picket",
             "David Picket: 29918 Redwood Dr (Adjuster Walk Through) FB"))
    assert run_doc.suggest_pics_stage("08-11-2026", "David Picket") == ""


def test_a_client_not_on_that_day_suggests_nothing(day):
    day(_job("Smith", "Smith: 1 Main St (Demo) FB"))
    assert run_doc.suggest_pics_stage("08-11-2026", "Jones") == ""


def test_no_run_doc_suggests_nothing(monkeypatch):
    monkeypatch.setattr(run_doc, "_find_run_doc_for_date", lambda d: None)
    assert run_doc.suggest_pics_stage("08-11-2026", "Smith") == ""


@pytest.mark.parametrize("date_str,client", [
    ("", "Smith"), ("08-11-2026", ""), ("not-a-date", "Smith"),
])
def test_junk_input_suggests_nothing(date_str, client):
    assert run_doc.suggest_pics_stage(date_str, client) == ""


def test_a_broken_run_doc_never_raises(monkeypatch):
    monkeypatch.setattr(run_doc, "_find_run_doc_for_date",
                        lambda d: "fake.docx")

    class _Hub:
        def parse_run_doc(self, path):
            raise OSError("share is down")

    import state_hub
    monkeypatch.setattr(state_hub, "hub", _Hub())
    assert run_doc.suggest_pics_stage("08-11-2026", "Smith") == ""


# ── name matching is shared with the label lookup ───────────────────

def test_a_near_name_still_matches(day):
    day(_job("Wilson Creek Winery",
             "Wilson Creek Winery: 1 Rd (Demo) FB"))
    assert run_doc.suggest_pics_stage("08-11-2026", "Wilson Creek") == "Demo"


def test_the_label_lookup_still_works(day):
    # Both helpers share one matcher; this is the older public one.
    day(_job("Smith", "Smith: 1 Main St (Demo) FB"))
    assert run_doc._activity_labels_from_run_doc("08-11-2026", "Smith") \
        == ["Demo"]
