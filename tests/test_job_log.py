"""The dated job-log comment.

    Monday 5/4/26

    Contents/Demo - Wendy/Priscilla/Vince

Tech naming is not cosmetic: roster LEADS are written as initials (ME,
FB, ML) and everyone else keeps their first name (Wendy, Priscilla,
Vince). Both forms appear in the office's real comments, and which one
you get says who the person is.
"""
import datetime as dt

import pytest

import job_log as jl


# ── the format, verbatim ───────────────────────────────────────────────
def test_matches_the_office_template():
    got = jl.comment_text(["Contents", "Demo"],
                          ["Wendy", "Priscilla", "Vince"], "2026-05-04")
    assert got["ok"]
    assert got["text"] == "Monday 5/4/26\n\nContents/Demo - Wendy/Priscilla/Vince"


def test_date_is_not_zero_padded_and_carries_the_year():
    """"5/4/26", not "05/04" — %-m is not portable to Windows and
    %#m is MSVC-only, so the padding comes off by hand."""
    assert jl.comment_text(["Demo"], ["Vince"], "2026-05-04")["text"] \
        .startswith("Monday 5/4/26")
    assert jl.comment_text(["Demo"], ["Vince"], "2026-12-25")["text"] \
        .startswith("Friday 12/25/26")


def test_blank_date_is_today():
    got = jl.comment_text(["Demo"], ["Vince"])
    assert got["date"] == dt.date.today().isoformat()


def test_a_bad_date_falls_back_to_today_rather_than_breaking():
    got = jl.comment_text(["Demo"], ["Vince"], "not-a-date")
    assert got["ok"] and got["date"] == dt.date.today().isoformat()


# ── leads vs helpers ───────────────────────────────────────────────────
@pytest.mark.parametrize("name,expect", [
    ("Mark E", "ME"), ("Fernando Baca", "FB"), ("Mark L", "ML"),
    ("Wendy", "Wendy"), ("Priscilla", "Priscilla"), ("Vince", "Vince"),
])
def test_lead_gets_initials_helper_keeps_first_name(name, expect):
    assert jl.tech_label(name) == expect


def test_a_mixed_crew_renders_both_forms():
    got = jl.comment_text(["Demo"], ["Mark E", "Vince", "Wendy"],
                          "2026-05-04")
    assert got["text"].endswith("Demo - ME/Vince/Wendy")


def test_techs_are_deduped_but_keep_their_order():
    """Order is how they were picked — the lead first when there is one,
    and re-sorting would fight that."""
    got = jl.comment_text(["Demo"], ["Vince", "Wendy", "Vince"], "2026-05-04")
    assert got["techs"] == "Vince/Wendy"


def test_activities_are_deduped():
    got = jl.comment_text(["Demo", "Demo", "Contents"], ["Vince"],
                          "2026-05-04")
    assert got["activities"] == "Demo/Contents"


def test_a_single_string_works_like_a_one_item_list():
    assert jl.comment_text("Monitor", "Mark E", "2026-05-04")["text"] \
        == "Monday 5/4/26\n\nMonitor - ME"


def test_no_techs_still_logs_the_activity():
    got = jl.comment_text(["Equipment Pull"], [], "2026-05-04")
    assert got["text"] == "Monday 5/4/26\n\nEquipment Pull"


def test_activity_is_required():
    assert jl.comment_text([], ["Vince"], "2026-05-04")["ok"] is False
    assert jl.comment_text(["  "], ["Vince"])["ok"] is False


def test_custom_activity_and_technician_are_accepted():
    got = jl.comment_text(["Set containment"], ["Jordan"],
                          "2026-08-24")
    assert got["ok"]
    assert got["text"] == ("Monday 8/24/26\n\n"
                           "Set containment - Jordan")


# ── the lead-also-monitored line ───────────────────────────────────────
def test_lead_monitored_on_a_non_monitor_day_adds_a_line():
    got = jl.comment_text(["Demo"], ["Wendy", "Vince"], "2026-05-04",
                          monitor_lead="Mark E")
    assert got["text"] == ("Monday 5/4/26\n\nDemo - Wendy/Vince"
                           "\n\nMonitor - ME")


def test_it_is_ignored_on_a_monitor_day():
    """Otherwise the same person appears twice on one day."""
    got = jl.comment_text(["Monitor"], ["Mark E"], "2026-05-04",
                          monitor_lead="Mark E")
    assert got["text"] == "Monday 5/4/26\n\nMonitor - ME"
    assert got["monitor_lead"] == ""


def test_it_is_ignored_when_monitor_is_one_of_several_activities():
    got = jl.comment_text(["Demo", "Monitor"], ["Vince"], "2026-05-04",
                          monitor_lead="Mark E")
    assert got["text"].count("Monitor") == 1


# ── the endpoints ──────────────────────────────────────────────────────
class _Api(__import__("audit_web").Api):
    def __init__(self):
        self._last_rows = []


def test_the_old_activity_comment_now_uses_the_same_format():
    """There used to be two builders — one rendering "Saturday 08/01"
    and one "Monday 5/4/26" — so the same day could reach a card written
    two different ways."""
    a = _Api()
    assert a.activity_comment_text("Monitor", "Mark E", "2026-05-04")["text"] \
        == a.job_log_comment_text(["Monitor"], ["Mark E"], "2026-05-04")["text"]


def test_options_mark_leads_and_todays_techs():
    a = _Api()
    a._last_rows = [{"client": "Smith, David", "techs": ["Vince"]}]
    opts = a.job_log_options("Smith, David")
    assert opts["ok"] and opts["activities"]
    by = {t["label"]: t for t in opts["techs"]}
    assert by.get("ME", {}).get("lead") is True
    assert by.get("Vince", {}).get("lead") is False
    assert by.get("Vince", {}).get("on_today") is True


def test_options_include_the_non_stage_activities():
    """Contents and Pack Out are logged but are not inspection stages."""
    acts = _Api().job_log_options()["activities"]
    for a in ("Contents", "Pack Out", "Pack Back", "Monitor", "Demo"):
        assert a in acts


def test_post_requires_a_card():
    assert _Api().post_job_log_comment("", ["Demo"], ["Vince"])["ok"] is False


def test_post_sends_the_previewed_string_verbatim(monkeypatch):
    import trello_client as tc
    sent = {}
    monkeypatch.setattr(tc, "post_comment",
                        lambda cid, text: sent.update(card=cid, text=text))
    a = _Api()
    preview = a.job_log_comment_text(["Contents", "Demo"],
                                     ["Wendy", "Vince"], "2026-05-04")
    res = a.post_job_log_comment("c1", ["Contents", "Demo"],
                                 ["Wendy", "Vince"], "2026-05-04")
    assert res["ok"] and sent["text"] == preview["text"]


def test_post_refuses_before_calling_trello_when_invalid(monkeypatch):
    import trello_client as tc
    monkeypatch.setattr(tc, "post_comment", lambda *a: pytest.fail(
        "posted an invalid comment"))
    assert _Api().post_job_log_comment("c1", [], ["Vince"])["ok"] is False


def test_snapshot_proxies_the_job_log_api():
    import snapshot_web
    for name in ("job_log_options", "job_log_comment_text",
                 "post_job_log_comment", "set_clipboard"):
        assert hasattr(snapshot_web.Api, name), f"snapshot_web missing {name}"


def test_shared_job_log_dialog_offers_custom_what_and_who_fields():
    import pathlib

    js = (pathlib.Path(__file__).parents[1] / "web_shared" /
          "audit_detail.js").read_text(encoding="utf-8")
    for control_id in ("jl-act-custom-toggle", "jl-act-custom",
                       "jl-tech-custom-toggle", "jl-tech-custom"):
        assert f'id="{control_id}"' in js
    assert 'customValue("#jl-act-custom")' in js
    assert 'customValue("#jl-tech-custom")' in js
    assert "picked.concat([custom])" in js
