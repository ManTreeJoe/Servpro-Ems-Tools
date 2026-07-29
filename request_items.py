"""Request paperwork / forms / scope / docusketch from a lead.

One dialog → posts a Trello comment @mentioning the lead with the tick-listed
items, hands back the Teams text to paste, and tracks the request so a
📨 "Requested Nd ago" chip surfaces on the Hygiene board + audit until it's
fulfilled. Pure logic; the UI lives in web_shared/request_items.js.
"""
from __future__ import annotations
import datetime as _dt

import persistence

# (key, label). Form names mirror audit_logic.REQUIRED_FORMS so the request
# matches what the audit tracks; docusketch + moisture map are the extras.
ITEMS = [
    ("atp",        "ATP (Auth to Perform)"),
    ("cif",        "CIF (Customer Info Form)"),
    ("cer",        "CER (Customer Equip Resp)"),
    ("cos",        "COS (Cert of Satisfaction)"),
    ("scope",      "Scope"),
    ("docusketch", "Docusketch scan"),
    ("moisture",   "Moisture map"),
]
_LABEL = dict(ITEMS)
# Compact labels for the composed message.
_SHORT = {
    "atp": "ATP", "cif": "CIF", "cer": "CER", "cos": "COS", "scope": "Scope",
    "docusketch": "Docusketch scan", "moisture": "moisture map",
}


def _now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def item_labels(keys) -> list:
    """Display labels for a list of item keys (unknowns dropped)."""
    return [_LABEL[k] for k in (keys or []) if k in _LABEL]


def _phrases(keys, other) -> list:
    parts = [_SHORT[k] for k in (keys or []) if k in _SHORT]
    if other and other.strip():
        parts.append(other.strip())
    return parts


def compose(job: str, keys, other: str = "", handle: str = "") -> dict:
    """Build the {trello, teams} message text for a request."""
    parts = _phrases(keys, other)
    items_txt = ", ".join(parts) if parts else "the outstanding items"
    h = (handle or "").strip()
    if h and not h.startswith("@"):
        h = "@" + h
    trello = (f"{h + ' ' if h else ''}📨 For **{job}** please provide: "
              f"{items_txt}. Thanks!")
    teams = f"Hey — for {job}, can you get me: {items_txt}? Thanks!"
    return {"trello": trello, "teams": teams}


def send(card_id: str, canon: str, keys, other: str = "",
         handle: str = "", client: str = "") -> dict:
    """Post the Trello comment (@mentioning `handle`) and record the request.
    Returns {ok, posted, teams, trello}. Teams text is copied by the UI —
    we don't send it. Never raises."""
    keys = [k for k in (keys or []) if k in _LABEL]
    # The audit passes a client name but no canon — resolve it to the SAME
    # canon the board uses so the 📨 Requested chip surfaces there too.
    if not canon and client:
        try:
            import ems_db
            _j = ems_db.find_job_by_name(client)
            canon = (_j and _j.get("canon_key")) or ems_db.canon_key(client)
        except Exception:
            canon = client
    job = client or canon or "this job"
    msg = compose(job, keys, other, handle)
    posted = False
    if card_id:
        try:
            import trello_client as tc
            tc.post_comment(card_id, msg["trello"])
            posted = True
        except Exception:
            posted = False
    try:
        state = persistence._load()
        store = state.setdefault("item_requests", {})
        store[canon] = {
            "items":        keys,
            "other":        (other or "").strip(),
            "handle":       (handle or "").strip(),
            "requested_at": _now_iso(),
            "posted":       posted,
        }
        # Remember handles for the dialog's dropdown (most-recent first, cap 8).
        h = (handle or "").strip()
        if h:
            hs = state.setdefault("request_handles", [])
            if h in hs:
                hs.remove(h)
            hs.insert(0, h)
            del hs[8:]
        persistence._save(state)
    except Exception:
        pass
    return {"ok": True, "posted": posted,
            "teams": msg["teams"], "trello": msg["trello"]}


def get_request(canon: str):
    """The tracked request for a job (or None)."""
    try:
        return (persistence._load().get("item_requests") or {}).get(canon)
    except Exception:
        return None


def recent_handles() -> list:
    try:
        return persistence._load().get("request_handles") or []
    except Exception:
        return []


def clear_request(canon: str) -> dict:
    """Drop a job's request record (fulfilled / cancelled)."""
    try:
        state = persistence._load()
        store = state.get("item_requests") or {}
        if canon in store:
            store.pop(canon, None)
            persistence._save(state)
    except Exception:
        pass
    return {"ok": True}
