"""Hygiene rules: lost-job (competitor) + equipment-still-on-site."""
import trello_hygiene as th


def _comment(date, text):
    return {"type": "commentCard", "date": date,
            "data": {"text": text}, "memberCreator": {"fullName": "A"}}


def _card(actions, closed=False):
    return {"id": "1", "name": "Club Pilates", "closed": closed,
            "labels": [], "idMembers": [], "members": [], "actions": actions}


def test_lost_job_flags_open_card():
    card = _card([_comment("2026-06-29T20:44:00.000Z",
                           "Hi Pablo, we moved ahead with another firm.")])
    v = th.rule_lost_job(card, "Estimating")
    assert v is not None and v["rule"] == "lost_job"


def test_lost_job_skips_closed_card():
    card = _card([_comment("2026-06-29T20:44:00.000Z",
                           "went with another firm")], closed=True)
    assert th.rule_lost_job(card, "Estimating") is None


def test_lost_job_ignores_normal_comment():
    card = _card([_comment("2026-06-20T00:00:00.000Z",
                           "Following up on the proposal, thanks.")])
    assert th.rule_lost_job(card, "Estimating") is None


def test_equipment_on_site_flags_outstanding():
    card = _card([
        _comment("2026-06-20T00:00:00.000Z", "Monitor visit, all dry."),
        _comment("2026-06-13T00:00:00.000Z",
                 "1 Air Scrubber placed in Pilates room. Equipment Placed: Yes"),
    ])
    v = th.rule_equipment_on_site(card, "WORK IN PROGRESS")
    assert v is not None and v["rule"] == "equipment_on_site"
    assert v["days_out"] >= 3


def test_equipment_cleared_when_picked_up():
    card = _card([
        _comment("2026-06-20T00:00:00.000Z", "Air scrubber picked up."),
        _comment("2026-06-13T00:00:00.000Z", "1 Air Scrubber placed in room"),
    ])
    assert th.rule_equipment_on_site(card, "WIP") is None
