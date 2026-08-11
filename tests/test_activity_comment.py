"""The dated activity comment (audit_web.Api.activity_comment_text /
post_activity_comment) and its stage picker.

The point of building the text in Python is that the preview shown in the
card and the string actually posted to Trello are the SAME string.

The format was unified onto `job_log` on 2026-08-11: one activity and one
tech is just the single-row case of the job-log comment, and having two
builders meant the same day could reach a card written two ways —
"Saturday 08/01" from here and "Monday 5/4/26" from the job-log dialog.
The office's format is the latter.

    Saturday 8/1/26

    Monitor - ME
"""
import datetime as dt

import pytest

import audit_web


class _Api(audit_web.Api):
    """Bare instance — these methods touch no audit state, so skip the
    real __init__ (which builds the whole panel's world)."""
    def __init__(self):
        pass


@pytest.fixture
def api():
    return _Api()


# ── shape ──────────────────────────────────────────────────────────────
def test_exact_handwritten_shape(api):
    r = api.activity_comment_text("Monitor", "ME", "2026-08-01")
    assert r["ok"]
    assert r["text"] == "Saturday 8/1/26\n\nMonitor - ME"


def test_date_is_unpadded_and_carries_the_year(api):
    # "1/5/26", not "01/05" — this is how the office writes it. %-m is
    # not portable to Windows, so the padding comes off by hand.
    r = api.activity_comment_text("Demo", "ME", "2026-01-05")
    assert r["text"].startswith("Monday 1/5/26\n\n")


def test_no_tech_drops_the_dash(api):
    r = api.activity_comment_text("Monitor", "", "2026-08-01")
    assert r["text"] == "Saturday 8/1/26\n\nMonitor"


def test_stage_is_required(api):
    r = api.activity_comment_text("", "ME", "2026-08-01")
    assert not r["ok"]
    assert "activity" in r["error"]


def test_blank_date_is_today(api):
    r = api.activity_comment_text("Monitor", "ME", "")
    assert r["date"] == dt.date.today().isoformat()


def test_unparseable_date_falls_back_to_today(api):
    # A bad value must not raise into the UI — it degrades to today.
    r = api.activity_comment_text("Monitor", "ME", "not-a-date")
    assert r["ok"]
    assert r["date"] == dt.date.today().isoformat()


# ── tech initials ──────────────────────────────────────────────────────
def test_full_name_is_written_as_initials(api):
    # The picker hands us roster full names; the office writes initials.
    r = api.activity_comment_text("Monitor", "Mark Escobar", "2026-08-01")
    assert r["text"].endswith("Monitor - ME")


def test_initials_pass_through_unchanged(api):
    r = api.activity_comment_text("Monitor", "ME", "2026-08-01")
    assert r["text"].endswith("Monitor - ME")


def test_unrostered_helper_keeps_their_name(api):
    # initials_for_name returns "" for non-leads — the `or tech` fallback
    # must keep the name rather than silently dropping who was on site.
    import audit_logic
    assert audit_logic.initials_for_name("Cesar") == ""
    r = api.activity_comment_text("Monitor", "Cesar", "2026-08-01")
    assert r["text"].endswith("Monitor - Cesar")


# ── stage picker ───────────────────────────────────────────────────────
def test_stage_list_comes_from_the_canonical_taxonomy(api):
    import stages
    r = api.list_activity_stages()
    assert r["ok"]
    assert r["stages"] == list(stages.LABELS)
    assert "Monitor" in r["stages"]


# ── posting ────────────────────────────────────────────────────────────
def test_post_requires_a_pinned_card(api):
    r = api.post_activity_comment("", "Monitor", "ME", "2026-08-01")
    assert not r["ok"]
    assert "card" in r["error"].lower()


def test_post_sends_the_previewed_string_verbatim(api, monkeypatch):
    """What gets posted must be byte-identical to what the preview
    showed — that is the whole reason the text is built in Python."""
    sent = {}
    import trello_client as tc
    monkeypatch.setattr(tc, "post_comment",
                        lambda cid, text: sent.update(card=cid, text=text))

    preview = api.activity_comment_text("Monitor", "Mark Escobar", "2026-08-01")
    r = api.post_activity_comment("card123", "Monitor", "Mark Escobar",
                                  "2026-08-01")
    assert r["ok"]
    assert sent["card"] == "card123"
    assert sent["text"] == preview["text"] == "Saturday 8/1/26\n\nMonitor - ME"


def test_post_surfaces_a_trello_failure(api, monkeypatch):
    import trello_client as tc

    def _boom(cid, text):
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(tc, "post_comment", _boom)

    r = api.post_activity_comment("card123", "Monitor", "ME", "2026-08-01")
    assert not r["ok"]
    assert "401" in r["error"]


def test_post_refuses_a_blank_stage_before_calling_trello(api, monkeypatch):
    import trello_client as tc
    monkeypatch.setattr(tc, "post_comment", lambda cid, text: pytest.fail(
        "posted despite an invalid comment"))
    r = api.post_activity_comment("card123", "", "ME", "2026-08-01")
    assert not r["ok"]


# ── snapshot parity (the recurring dead-button trap) ───────────────────
def test_snapshot_proxies_every_activity_method():
    """audit_detail.js is ONE card rendered by audit AND snapshot. A
    method the snapshot window doesn't proxy is a dead button there."""
    import snapshot_web
    for name in ("list_activity_stages", "activity_comment_text",
                 "post_activity_comment", "list_techs"):
        assert hasattr(snapshot_web.Api, name), f"snapshot_web missing {name}"
