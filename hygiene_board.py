"""Simple Hygiene job board — one row per active job with four admin
milestones, auto-detected where the data already exists and one-click
markable where it doesn't:

  • DocuSign requested   ← docusign_requests log (auto) / manual
  • Initial paperwork sent ← manual (no existing source)
  • Final paperwork sent  ← docusign_requests paperwork_sent_at (auto) / manual
  • Weekly check-in       ← weekly_checkins / persistence weekly_note_sent (auto)

Replaces the wall of Hygiene sections with a single at-a-glance board.
Manual stamps live in persistence under `hygiene_milestones[canon]`.
Pure data layer — no UI. Best-effort throughout; a missing module never
breaks the board.
"""
from __future__ import annotations
import datetime as _dt
import time as _time

import ems_db
import persistence

_MILESTONE_FIELD = {
    "ds_requested": "ds_requested_at",
    "initial_sent": "initial_sent_at",
    "final_sent":   "final_sent_at",
}

# The board only shows jobs still ACTIVE — i.e. whose Trello card currently
# lives on the WIP or Estimating board. Match board names loosely so a
# rename ("WIP", "Work In Progress", "Estimating") still resolves.
_ACTIVE_BOARD_MARKERS = ("WIP", "IN PROGRESS", "ESTIMAT")
_ACTIVE_CACHE: dict = {"ids": None, "ts": 0.0}
_ACTIVE_TTL = 300.0            # seconds — re-renders after a mark reuse this


def _active_boards():
    """{"all": card ids on WIP+Estimating, "estimating": subset on the
    Estimating board}, or None when Trello can't be reached (fail-open →
    don't over-filter to an empty board on a transient hiccup). Cached
    ~5 min so a click's re-render doesn't re-hit Trello. Weekly check-ins
    only apply to the `estimating` subset."""
    now = _time.time()
    if (_ACTIVE_CACHE["ids"] is not None
            and (now - _ACTIVE_CACHE["ts"]) < _ACTIVE_TTL):
        return _ACTIVE_CACHE["ids"]
    try:
        import trello_client as tc
        boards = tc.list_boards() or []
    except Exception:
        return None
    all_ids: set = set()
    est_ids: set = set()
    for b in boards:
        name = (b.get("name") or "").upper()
        is_est = "ESTIMAT" in name
        is_wip = ("WIP" in name or "IN PROGRESS" in name)
        if not (is_est or is_wip):
            continue
        bid = b.get("id")
        if not bid:
            continue
        try:
            cards = tc._call(f"/boards/{bid}/cards",
                             params={"fields": "id"}) or []
        except Exception:
            continue
        for c in cards:
            cid = c.get("id")
            if not cid:
                continue
            all_ids.add(cid)
            if is_est:
                est_ids.add(cid)
    res = {"all": all_ids, "estimating": est_ids}
    _ACTIVE_CACHE["ids"] = res
    _ACTIVE_CACHE["ts"] = now
    return res


def _today() -> str:
    return _dt.date.today().isoformat()


def _date_of(iso: str | None) -> str:
    """YYYY-MM-DD slice of an ISO timestamp, or '' when unset."""
    s = (iso or "").strip()
    return s[:10] if len(s) >= 10 else ""


def _manual_store() -> dict:
    try:
        return persistence._load().get("hygiene_milestones") or {}
    except Exception:
        return {}


def board_rows() -> list[dict]:
    """One dict per active job (those with a linked Trello card), each
    carrying the four milestone dates + a weekly-check-in overdue flag.
    Overdue check-ins sort to the top, then alphabetical by job name."""
    try:
        import docusign_requests as _dsr
        ds = _dsr._load() or {}
    except Exception:
        ds = {}
    try:
        weekly = persistence.get_weekly_notes_sent() or {}
    except Exception:
        weekly = {}
    try:
        import weekly_checkins as _wc
    except Exception:
        _wc = None
    manual = _manual_store()
    try:
        import request_items as _ri
    except Exception:
        _ri = None
    # Only jobs still on the WIP / Estimating boards (None = fail-open).
    active = _active_boards()
    active_all = active["all"] if active else None
    active_est = active["estimating"] if active else None

    today = _dt.date.today()
    rows = []
    for j in ems_db.iter_jobs():
        canon = j.get("canon_key") or ""
        if not canon:
            continue
        try:
            card = ems_db.get_link(canon, ems_db.LINK_TRELLO) or ""
        except Exception:
            card = ""
        if not card:
            continue                      # board = active jobs w/ a card
        if active_all is not None and card not in active_all:
            continue                      # not on WIP / Estimating → skip
        m = manual.get(canon, {})
        dsr = ds.get(card, {})
        # Weekly check-ins only apply to Estimating-board jobs. When Trello
        # is unreachable (active_est is None) fall open → apply to all.
        weekly_applies = (active_est is None) or (card in active_est)
        overdue = False
        if weekly_applies and _wc is not None:
            try:
                overdue = bool(_wc.is_due(card))
            except Exception:
                overdue = False
        # Outstanding item request (📨 Requested Nd ago).
        requested_at, requested_days, requested_items = "", None, []
        if _ri is not None:
            req = _ri.get_request(canon)
            if req and req.get("requested_at"):
                requested_at = req["requested_at"][:10]
                requested_items = _ri.item_labels(req.get("items"))
                if req.get("other"):
                    requested_items.append(req["other"])
                try:
                    requested_days = (today - _dt.date.fromisoformat(
                        requested_at)).days
                except Exception:
                    requested_days = None
        rows.append({
            "canon":          canon,
            "card_id":        card,
            "job":            j.get("display_name") or canon,
            # DocuSign requested: the log's `requested`, else a manual stamp.
            "ds_requested":   _date_of(dsr.get("requested")) or m.get("ds_requested_at", ""),
            "ds_state":       dsr.get("state", ""),
            # Initial paperwork: manual only (no existing source).
            "initial_sent":   m.get("initial_sent_at", ""),
            # Final paperwork: DocuSign paperwork_sent_at, else a manual stamp.
            "final_sent":     _date_of(dsr.get("paperwork_sent_at")) or m.get("final_sent_at", ""),
            # Weekly check-in: only for Estimating jobs; last note + overdue.
            "weekly_applies": weekly_applies,
            "last_checkin":   _date_of(weekly.get(card)) if weekly_applies else "",
            "checkin_overdue": overdue,
            # Outstanding item request.
            "requested_at":   requested_at,
            "requested_days": requested_days,
            "requested_items": requested_items,
        })
    rows.sort(key=lambda r: (not r["checkin_overdue"], r["job"].lower()))
    return rows


def mark_milestone(canon: str, milestone: str, *, card_id: str = "",
                   clear: bool = False) -> dict:
    """Stamp today's date (or clear) for one milestone on one job.

    Weekly check-ins route through `weekly_checkins.mark_weekly_note_sent`
    (the canonical store); the other three write to the manual
    `hygiene_milestones` store. Returns {ok, date}."""
    if milestone == "weekly_checkin":
        if not card_id:
            return {"ok": False, "error": "no card for weekly check-in"}
        try:
            import weekly_checkins as _wc
            _wc.mark_weekly_note_sent(card_id)
            return {"ok": True, "date": _today()}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    field = _MILESTONE_FIELD.get(milestone)
    if not field or not canon:
        return {"ok": False, "error": "unknown milestone / no job"}
    try:
        state = persistence._load()
        store = state.setdefault("hygiene_milestones", {})
        rec = store.setdefault(canon, {})
        if clear:
            rec.pop(field, None)
            date = ""
        else:
            date = _today()
            rec[field] = date
        persistence._save(state)
        return {"ok": True, "date": date}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
