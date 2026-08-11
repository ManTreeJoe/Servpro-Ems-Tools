"""The database is the source of truth.

Two properties, both load-bearing:

  The local write happens FIRST, before any network call. It used to run
  at the END, after the Trello push — so a crash or a hang mid-push lost
  the edit. The docstring already claimed "writes locally FIRST", which
  is how it went unnoticed.

  Where the Hub and the card disagree, the HUB WINS — but says so.
  Overwriting somebody's card edit is the intended rule; doing it
  silently is not, because you cannot put back what you never knew you
  replaced.
"""
import pytest

import job_settings as js


@pytest.fixture
def job(tmp_path, monkeypatch):
    """A real job in a scratch DB, with a pinned card."""
    import ems_db_sqlite as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ems_jobs.db"))
    db._init_schema()
    key = db.upsert_job(display_name="Smith, David - Mercury")
    db.set_link(key, db.LINK_TRELLO, "card1")
    return key


@pytest.fixture
def trello(monkeypatch):
    """A fake card whose desc we can inspect and fail on demand."""
    state = {"desc": "", "pushes": 0, "fail": False, "order": []}

    def _get_card(cid, **k):
        state["order"].append("read")
        return {"id": cid, "desc": state["desc"]}

    def _update(cid, desc):
        state["order"].append("push")
        state["pushes"] += 1
        if state["fail"]:
            raise RuntimeError("Trello 503")
        state["desc"] = desc
        return True

    import trello_client as tc
    monkeypatch.setattr(tc, "get_card", _get_card)
    monkeypatch.setattr(tc, "update_card_desc", _update)
    return state


def _saved(key):
    import ems_db
    return js.stored_values(ems_db.get_job(key))


# ── DB first ───────────────────────────────────────────────────────────
def test_the_local_write_lands_even_when_trello_fails(job, trello):
    trello["fail"] = True
    res = js.save(job, {"carrier": "Mercury", "adjuster_name": "Jane Doe"})
    assert res["ok"]
    assert res["pending_push"] is True
    assert _saved(job)["adjuster_name"] == "Jane Doe"


def test_the_local_write_happens_before_the_push(job, trello, monkeypatch):
    """Not just 'eventually' — before. A hang in update_card_desc must
    not be able to lose the edit."""
    seen = {}
    real_persist = js._persist

    def _spy(canon_key, child_name, values, meta):
        seen.setdefault("persist_at", len(trello["order"]))
        return real_persist(canon_key, child_name, values, meta)
    monkeypatch.setattr(js, "_persist", _spy)

    js.save(job, {"carrier": "Mercury"})
    # No push had happened yet when the first persist ran.
    assert "push" not in trello["order"][:seen["persist_at"]]


def test_a_crash_mid_push_still_leaves_the_value_saved(job, trello,
                                                       monkeypatch):
    import trello_client as tc

    def _boom(cid, desc):
        raise KeyboardInterrupt("machine went down")
    monkeypatch.setattr(tc, "update_card_desc", _boom)
    with pytest.raises(KeyboardInterrupt):
        js.save(job, {"carrier": "Mercury"})
    assert _saved(job)["carrier"] == "Mercury"


# ── the Hub wins, and says so ──────────────────────────────────────────
def test_hub_value_overwrites_the_card(job, trello):
    trello["desc"] = "**INSURANCE INFORMATION**\nINSURANCE COMPANY: AAA\n"
    js.save(job, {"carrier": "Mercury"})
    assert "Mercury" in trello["desc"]
    assert res_carrier(job) == "Mercury"


def res_carrier(key):
    return _saved(key)["carrier"]


def test_overwriting_an_untouched_card_is_not_flagged(job, trello):
    """No baseline yet, or the card matches it — nobody else edited, so
    there is nothing to warn about."""
    trello["desc"] = "**INSURANCE INFORMATION**\nINSURANCE COMPANY: AAA\n"
    res = js.save(job, {"carrier": "Mercury"})
    assert res["clobbered"] == []


def test_overwriting_someone_elses_card_edit_is_reported(job, trello):
    # First save establishes the baseline: card and Hub agree on AAA.
    trello["desc"] = "**INSURANCE INFORMATION**\nINSURANCE COMPANY: AAA\n"
    js.save(job, {"carrier": "AAA"})
    # Somebody edits the card directly.
    trello["desc"] = "**INSURANCE INFORMATION**\nINSURANCE COMPANY: Farmers\n"
    # We save something different. Hub wins, but it must be reported.
    res = js.save(job, {"carrier": "Mercury"})
    assert "Mercury" in trello["desc"]
    labels = [c["label"] for c in res["clobbered"]]
    assert "Carrier" in labels
    got = next(c for c in res["clobbered"] if c["label"] == "Carrier")
    assert got["was"] == "Farmers" and got["now"] == "Mercury"


def test_a_field_we_did_not_touch_is_not_reported(job, trello):
    trello["desc"] = ("**INSURANCE INFORMATION**\nINSURANCE COMPANY: AAA\n"
                      "CLAIM NUMBER: C-1\n")
    js.save(job, {"carrier": "AAA", "claim_number": "C-1"})
    trello["desc"] = ("**INSURANCE INFORMATION**\nINSURANCE COMPANY: AAA\n"
                      "CLAIM NUMBER: C-2\n")
    res = js.save(job, {"carrier": "AAA", "claim_number": "C-2"})
    # We agree with the card on both — nothing was overwritten.
    assert res["clobbered"] == []


# ── the baseline still only advances on a real push ────────────────────
def test_baseline_does_not_advance_on_a_failed_push(job, trello):
    """Advancing it would make the next merge read our unsent edit as
    already agreed and discard whatever the card says."""
    import ems_db
    trello["fail"] = True
    js.save(job, {"carrier": "Mercury"})
    base = js.stored_base(ems_db.get_job(job))
    assert (base.get("carrier") or "") != "Mercury"


def test_baseline_advances_on_success(job, trello):
    import ems_db
    js.save(job, {"carrier": "Mercury"})
    base = js.stored_base(ems_db.get_job(job))
    assert base.get("carrier") == "Mercury"


def test_no_card_still_saves(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "e.db"))
    db._init_schema()
    key = db.upsert_job(display_name="No Card Job")
    res = js.save(key, {"carrier": "AAA"})
    assert res["ok"] and res["pushed"] is False
    assert _saved(key)["carrier"] == "AAA"
