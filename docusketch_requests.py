"""Docusketch-pending tracker.

When the user has *asked* for a Docusketch on a job but the zip isn't
back yet, they click "Request via Trello" in the Docusketch import
dialog. This module:

  1. Posts a comment on the matching Trello card ("📐 Docusketch was
     requested") so the audit trail lives on the card.
  2. Records the request in persistence so the Hygiene panel surfaces
     it in a "📐 Docusketch pending" section every day until cleared.
  3. Auto-clears when a Docusketch zip is successfully imported for
     the matching card — the import flow calls `resolve(card_id)`.

The pending list never auto-expires. It's a daily nag until the
docusketch is actually received OR the user manually clicks "Resolved"
in the Hygiene row (e.g., they decided not to use one after all).

Public API:
    request(card_id, *, client_name="", post_comment=True) -> entry|None
    resolve(card_id) -> None
    pending_requests() -> [{card_id, client, card_name, card_url,
                              lane, requested, days_pending}, ...]
    is_pending(card_id) -> bool
    DEFAULT_NOTE — the comment text posted to Trello
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import persistence as per
import trello_client as tc


DEFAULT_NOTE = "📐 Docusketch was requested"


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _load() -> dict[str, dict[str, Any]]:
    raw = per.get("docusketch_requests") or {}
    return raw if isinstance(raw, dict) else {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    per.set_value("docusketch_requests", data)


def request(card_id: str, *, client_name: str = "",
            post_comment: bool = True) -> dict[str, Any] | None:
    """Record a pending docusketch request for a Trello card. Posts the
    Trello comment when `post_comment` is True (default). Returns the
    recorded entry, or None if the card couldn't be looked up."""
    if not card_id:
        return None
    try:
        card = tc.get_card(card_id, actions_limit=0)
    except Exception:
        card = None
    if not card:
        return None

    posted_ok = True
    if post_comment:
        try:
            tc.post_comment(card_id, DEFAULT_NOTE)
        except Exception:
            # Posting failed — still record locally so the reminder
            # surfaces; user can manually post the comment from the
            # card if needed.
            posted_ok = False

    lane_name = ""
    try:
        lane_name = tc.get_lane_name(card.get("idBoard"), card.get("idList"))
    except Exception:
        pass

    entry = {
        "card_id":   card_id,
        "client":    client_name or card.get("name", ""),
        "card_name": card.get("name", ""),
        "card_url":  card.get("shortUrl", ""),
        "board_id":  card.get("idBoard", ""),
        "list_id":   card.get("idList", ""),
        "lane":      lane_name,
        "requested": _utcnow().isoformat(timespec="seconds"),
        "comment_posted": posted_ok,
    }
    data = _load()
    data[card_id] = entry
    _save(data)
    return entry


def resolve(card_id: str) -> None:
    """Mark a docusketch request resolved. Removes the entry so it stops
    surfacing. Called from the Hygiene panel ✓ button AND from the
    Docusketch import flow when a zip is successfully extracted."""
    if not card_id:
        return
    data = _load()
    if card_id in data:
        data.pop(card_id, None)
        _save(data)


def is_pending(card_id: str) -> bool:
    return bool(card_id) and card_id in _load()


def pending_requests() -> list[dict[str, Any]]:
    """Return all unresolved docusketch requests, sorted by oldest first
    (most overdue at the top). Each entry includes `days_pending` so the
    Hygiene row can display 'requested 3d ago'."""
    data = _load()
    out: list[dict[str, Any]] = []
    now = _utcnow()
    for card_id, entry in data.items():
        requested = _parse_iso(entry.get("requested", ""))
        days = (now - requested).days if requested else 0
        item = dict(entry)
        item["card_id"] = card_id
        item["days_pending"] = max(0, days)
        out.append(item)
    out.sort(key=lambda e: -e.get("days_pending", 0))
    return out


# ── WIP-needs-docusketch detection ──────────────────────────────────────────
# Trigger rule (user direction): when a job first hits the WORK IN
# PROGRESS lane, we need to request a Docusketch BEFORE the work
# starts. The Hygiene panel surfaces these as a daily "📐 Docusketch
# needed (WIP)" section so the operator can one-click Request — the
# row then graduates to the existing "📐 Docusketch pending" section.
_WIP_LANE_SUBSTRINGS = ("work in progress",)
_WIP_DISMISS_KEY = "docusketch_wip_dismissed"


def is_wip_dismissed(card_id: str) -> bool:
    """True when the operator clicked ✕ Dismiss on a WIP-needs-docusketch
    row for this card. Dismissals persist across sessions so a card
    that already has a Docusketch handled outside the tracker doesn't
    re-surface every scan."""
    if not card_id:
        return False
    raw = per.get(_WIP_DISMISS_KEY) or []
    return card_id in raw if isinstance(raw, list) else False


def dismiss_wip_card(card_id: str) -> None:
    """Mark a card as not-needing-a-docusketch-request even though
    it's in WIP. Used when a Docusketch was already done outside the
    tracker (e.g. older job carried over from before the tool ran)."""
    if not card_id:
        return
    raw = per.get(_WIP_DISMISS_KEY) or []
    if not isinstance(raw, list):
        raw = []
    if card_id in raw:
        return
    raw.append(card_id)
    per.set_value(_WIP_DISMISS_KEY, raw)


def find_wip_cards_needing_docusketch():
    """Walk the pipeline lifecycle table for cards currently in a
    'WORK IN PROGRESS' lane that don't yet have a pending Docusketch
    request AND haven't been manually dismissed. Returns rows shaped
    for the Hygiene panel renderer.

    Source-of-truth is ``ems_db.job_lifecycle`` — populated by every
    Hygiene scan via the pipeline_stages piggyback, so this filter
    sees the same cards Hygiene already walked (no extra Trello API
    calls). Sorted longest-in-WIP first so the most-overdue rows
    surface at the top.
    """
    try:
        import ems_db as _db
        import pipeline_stages as _ps
    except ImportError:
        return []
    pending_ids = {e["card_id"] for e in pending_requests()}
    try:
        rows = _db.lifecycle_list(paid_window_days=30)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        lane = (r.get("list_name") or "").lower()
        if not any(s in lane for s in _WIP_LANE_SUBSTRINGS):
            continue
        cid = r.get("card_id") or ""
        if not cid:
            continue
        if cid in pending_ids:
            continue  # already requested → existing 'pending' section
        if is_wip_dismissed(cid):
            continue
        out.append({
            "card_id":    cid,
            "client":     r.get("client_display") or "",
            "card_url":   r.get("card_url") or "",
            "board_name": r.get("board_name") or "",
            "list_name":  r.get("list_name") or "",
            "days_in_wip": _ps.days_in_stage(r),
        })
    out.sort(key=lambda r: -(r.get("days_in_wip") or 0))
    return out


def find_card_for_client(client_name: str) -> dict[str, Any] | None:
    """Best-effort Trello card lookup by client name. Used by the
    Docusketch dialog button when an audit row gives us a name but no
    card_id. Prefers OPEN cards on non-AR boards (an active job is a
    better match than a paid/closed AR row of the same insured)."""
    if not client_name:
        return None
    try:
        hits = tc.find_cards_by_name(client_name, max_results=8)
    except Exception:
        return None
    if not hits:
        return None
    # Single hit — done. Auto-pin this card to the client so every
    # subsequent tool (job notes, audit's Trello button, hygiene
    # right-click) finds it without re-searching. Only pins when the
    # client has no existing pin: never overwrite the user's manual
    # pick. Multi-hit case explicitly skips this — user direction was
    # "auto-pin if there's only one, manual choice when there are
    # multiple."
    if len(hits) == 1:
        _maybe_auto_pin(client_name, hits[0])
        return hits[0]
    # Multiple hits — prefer non-AR-board, non-closed but DO NOT
    # auto-pin (the user wants to choose when results are ambiguous).
    ar_keyword = "ar"
    open_non_ar = []
    for h in hits:
        board_name = (h.get("board_name") or "").lower()
        closed = bool(h.get("closed"))
        if not closed and ar_keyword not in board_name:
            open_non_ar.append(h)
    if open_non_ar:
        return open_non_ar[0]
    # Fall through to first hit.
    return hits[0]


def _maybe_auto_pin(client_name: str, hit: dict) -> None:
    """Pin `hit['card_id']` to `client_name` IFF the client has no
    existing pin. Never overwrites — a user-set pin always wins. Best-
    effort: persistence write failures are swallowed so a failed pin
    can't crash the lookup that called us."""
    try:
        import persistence as _per
        existing = _per.get_trello_card_ids(client_name) or []
        if existing:
            return  # already pinned (manually or from a prior single-hit)
        card_id = (hit or {}).get("card_id") or ""
        if not card_id:
            return
        _per.set_trello_card_id(client_name, card_id)
    except Exception:
        pass
