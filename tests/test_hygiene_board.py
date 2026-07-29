"""Simple Hygiene job board — merge of auto-detected + manual milestones."""
import ems_db
import persistence
import docusign_requests
import weekly_checkins
import hygiene_board as hb


def _setup(monkeypatch, jobs, links, ds, weekly, state, active=None):
    monkeypatch.setattr(ems_db, "iter_jobs", lambda: jobs)
    monkeypatch.setattr(ems_db, "get_link",
                        lambda canon, t: links.get(canon, ""))
    monkeypatch.setattr(docusign_requests, "_load", lambda: ds)
    monkeypatch.setattr(persistence, "get_weekly_notes_sent", lambda: weekly)
    monkeypatch.setattr(weekly_checkins, "is_due",
                        lambda card, **k: card == "cardB")
    # manual store lives in persistence state
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    # Active-board lookup: default None (fail-open) unless a test scopes it.
    # `active` (when given) is a set of card ids treated as WIP+Estimating;
    # pass an (all, est) tuple to distinguish the Estimating subset.
    def _boards():
        if active is None:
            return None
        if isinstance(active, tuple):
            return {"all": set(active[0]), "estimating": set(active[1])}
        return {"all": set(active), "estimating": set(active)}
    monkeypatch.setattr(hb, "_active_boards", _boards)


def test_board_merges_sources(monkeypatch):
    jobs = [
        {"canon_key": "mims stewart", "display_name": "Mims, Stewart"},
        {"canon_key": "doe jane", "display_name": "Doe, Jane"},
        {"canon_key": "no card", "display_name": "No Card"},
    ]
    links = {"mims stewart": "cardA", "doe jane": "cardB"}   # 3rd has no card
    ds = {"cardA": {"requested": "2026-07-20T10:00:00",
                    "paperwork_sent_at": "2026-07-22T09:00:00",
                    "state": "pending_signature"}}
    weekly = {"cardA": "2026-07-21T08:00:00"}
    state = {"hygiene_milestones": {"mims stewart": {"initial_sent_at": "2026-07-14"}}}
    _setup(monkeypatch, jobs, links, ds, weekly, state)

    rows = hb.board_rows()
    assert len(rows) == 2                       # 'No Card' excluded
    by = {r["job"]: r for r in rows}
    mims = by["Mims, Stewart"]
    assert mims["ds_requested"] == "2026-07-20"      # auto from DS log
    assert mims["final_sent"] == "2026-07-22"        # auto from DS log
    assert mims["initial_sent"] == "2026-07-14"      # manual store
    assert mims["last_checkin"] == "2026-07-21"
    assert mims["checkin_overdue"] is False
    # Doe has no DS/manual → blanks, and is overdue (is_due → cardB).
    doe = by["Doe, Jane"]
    assert doe["ds_requested"] == "" and doe["final_sent"] == ""
    assert doe["checkin_overdue"] is True
    # Overdue sorts first.
    assert rows[0]["job"] == "Doe, Jane"


def test_only_active_board_cards_shown(monkeypatch):
    jobs = [
        {"canon_key": "mims stewart", "display_name": "Mims, Stewart"},
        {"canon_key": "doe jane", "display_name": "Doe, Jane"},
    ]
    links = {"mims stewart": "cardA", "doe jane": "cardB"}
    # Only cardA is on WIP/Estimating → Doe (cardB) is dropped.
    _setup(monkeypatch, jobs, links, {}, {}, {}, active={"cardA"})
    rows = hb.board_rows()
    assert [r["job"] for r in rows] == ["Mims, Stewart"]


def test_weekly_only_applies_to_estimating(monkeypatch):
    jobs = [
        {"canon_key": "est job", "display_name": "Est Job"},
        {"canon_key": "wip job", "display_name": "WIP Job"},
    ]
    links = {"est job": "cardE", "wip job": "cardW"}
    weekly = {"cardE": "2026-07-10T00:00:00", "cardW": "2026-07-10T00:00:00"}
    # Both on the boards; only cardE is on Estimating.
    _setup(monkeypatch, jobs, links, {}, weekly, {},
           active=({"cardE", "cardW"}, {"cardE"}))
    by = {r["job"]: r for r in hb.board_rows()}
    assert by["Est Job"]["weekly_applies"] is True
    assert by["Est Job"]["last_checkin"] == "2026-07-10"
    # WIP job: weekly doesn't apply → no last_checkin, not overdue.
    assert by["WIP Job"]["weekly_applies"] is False
    assert by["WIP Job"]["last_checkin"] == ""
    assert by["WIP Job"]["checkin_overdue"] is False


def test_mark_manual_milestone(monkeypatch):
    state = {}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    res = hb.mark_milestone("mims stewart", "initial_sent")
    assert res["ok"] and res["date"]
    assert state["hygiene_milestones"]["mims stewart"]["initial_sent_at"] == res["date"]
    # Clear it.
    res2 = hb.mark_milestone("mims stewart", "initial_sent", clear=True)
    assert res2["ok"] and res2["date"] == ""
    assert "initial_sent_at" not in state["hygiene_milestones"]["mims stewart"]


def test_mark_weekly_routes_to_weekly_module(monkeypatch):
    hit = {}
    monkeypatch.setattr(weekly_checkins, "mark_weekly_note_sent",
                        lambda card: hit.setdefault("card", card))
    res = hb.mark_milestone("mims stewart", "weekly_checkin", card_id="cardA")
    assert res["ok"] and hit["card"] == "cardA"
    # No card → error, not a crash.
    assert hb.mark_milestone("x", "weekly_checkin")["ok"] is False


def test_unknown_milestone(monkeypatch):
    monkeypatch.setattr(persistence, "_load", lambda: {})
    monkeypatch.setattr(persistence, "_save", lambda s: None)
    assert hb.mark_milestone("x", "bogus")["ok"] is False
