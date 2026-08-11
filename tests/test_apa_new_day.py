"""APA new-day behaviour and the name filter.

Three complaints:
  * the name filter was unreliable
  * a new day kept yesterday's statuses instead of going back to pending
  * a new day didn't re-check Trello, so carried items kept yesterday's
    section routing
"""
import pytest

import apa_logic as apa
import apa_web


# ── restamping a carried item ──────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("Brew, Brian - AAA-Testing/Clearance-extended",
     "Brew, Brian - AAA-Testing/Clearance-pending"),
    ("Smith, David - Mercury-uploaded", "Smith, David - Mercury-pending"),
    ("Doe, Jane - AAA-JUAN-pending upload", "Doe, Jane - AAA-JUAN-pending"),
    ("Jones, Amy - AAA", "Jones, Amy - AAA-pending"),
])
def test_restamp_replaces_the_status(text, expected):
    assert apa_web._restamp(text, False, "pending")[0] == expected


def test_restamp_does_not_stack_statuses():
    """Appending without peeling gives
    "...-Testing/Clearance-extended-pending"."""
    out = apa_web._restamp("Brew, Brian - AAA-extended", False, "pending")[0]
    assert out.count("pending") == 1
    assert "extended" not in out


def test_restamp_keeps_the_sub():
    out = apa_web._restamp("Doe, Jane - AAA-JUAN-extended", False, "pending")[0]
    assert "-JUAN-" in out


def test_restamp_rederives_highlight_from_status():
    """A stale yellow row that no longer matches its status is the bug
    that used to drag finished jobs forward."""
    _, hi = apa_web._restamp("Smith, David - AAA-uploaded", False, "pending")
    assert hi is True                      # pending highlights
    _, hi2 = apa_web._restamp("Smith, David - AAA-pending", True, "uploaded")
    assert hi2 is False                    # uploaded does not


def test_restamp_with_blank_status_is_a_passthrough():
    assert apa_web._restamp("Brew, Brian - AAA-extended", True, "") == \
        ("Brew, Brian - AAA-extended", True)


def test_restamp_survives_junk():
    assert apa_web._restamp("", False, "pending")[0] == ""


# ── the `base` field the name filter matches on ────────────────────────
def test_items_expose_the_bare_name():
    rows = [("Brew, Brian - AAA-Testing/Clearance-extended", True)]
    got = apa_web._items_for_section(rows)[0]
    assert got["base"] == "Brew, Brian - AAA"
    assert got["text"].endswith("-extended")     # stored text untouched


def test_hyphenated_surname_is_not_mangled():
    """A split on "-" would cut Garcia-Vargas in half."""
    rows = [("Garcia-Vargas, Antonio - Farmers-pending", True)]
    assert apa_web._items_for_section(rows)[0]["base"] == \
        "Garcia-Vargas, Antonio - Farmers"


def test_estimator_sub_is_peeled_from_the_name():
    rows = [("Doe, Jane - AAA-JUAN-pending upload", True)]
    assert apa_web._items_for_section(rows)[0]["base"] == "Doe, Jane - AAA"


# ── create_doc: new day resets status + re-checks Trello ───────────────
class _Api(apa_web.Api):
    def __init__(self):
        self.lane_calls = []

    def refresh_doc_lanes(self, date_iso=""):
        self.lane_calls.append(date_iso)
        return {"ok": True, "moved": 2, "checked": 5, "doc": {"stub": True}}


@pytest.fixture
def stub_docs(monkeypatch, tmp_path):
    """A prior doc with one item per carry-status, and capture of what
    gets written for the new day."""
    written = {}
    prior = [
        ("Brew, Brian - AAA-extended", False),
        ("Doe, Jane - AAA-pending upload", True),
        ("Smith, David - AAA-uploaded", True),     # done — must NOT carry
    ]

    def _path(d=None):
        # today missing, yesterday present
        import datetime as dt
        return str(tmp_path / ("prior.docx" if d and d < dt.date.today()
                               else "today.docx"))
    monkeypatch.setattr(apa, "doc_path_for_today", _path)
    monkeypatch.setattr(apa_web.os.path, "isfile",
                        lambda p: p.endswith("prior.docx"))
    monkeypatch.setattr(apa, "parse_existing_doc",
                        lambda p, *a, **k: {"Final Uploads": list(prior)})
    monkeypatch.setattr(apa, "write_doc",
                        lambda p, d, secs, *a, **k: written.update(secs))
    monkeypatch.setattr(apa_web, "_doc_payload_for", lambda d: {"ok": True})
    monkeypatch.setattr(apa_web.os, "makedirs", lambda *a, **k: None)
    return written


def test_new_day_resets_carried_items_to_pending(stub_docs):
    api = _Api()
    res = api.create_doc("2026-08-12")
    assert res["ok"] and res["created"]
    carried = stub_docs.get("Final Uploads") or []
    texts = [t for t, _ in carried]
    assert all(t.endswith("-pending") for t in texts), texts
    assert not any("extended" in t for t in texts)
    # the uploaded row is still left behind
    assert not any("Smith, David" in t for t in texts)


def test_new_day_rechecks_trello_by_default(stub_docs):
    api = _Api()
    res = api.create_doc("2026-08-12")
    assert api.lane_calls == ["2026-08-12"]
    assert res["lanes_moved"] == 2


def test_lane_refresh_can_be_turned_off(stub_docs):
    api = _Api()
    api.create_doc("2026-08-12", refresh_lanes=False)
    assert api.lane_calls == []


def test_status_reset_can_be_turned_off(stub_docs):
    api = _Api()
    api.create_doc("2026-08-12", reset_status="")
    texts = [t for t, _ in stub_docs.get("Final Uploads") or []]
    assert any("extended" in t for t in texts)


def test_a_trello_failure_does_not_lose_the_doc(stub_docs):
    """The .docx is already on the share by then — a lane refresh that
    blows up must be reported, not fatal."""
    class _Broken(_Api):
        def refresh_doc_lanes(self, date_iso=""):
            raise RuntimeError("Trello 429")
    res = _Broken().create_doc("2026-08-12")
    assert res["ok"] and res["created"]
    assert "429" in res["lanes_error"]
