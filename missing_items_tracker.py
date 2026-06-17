"""Missing-items tracker — items the snapshot flagged as not present.

When a snapshot is generated, the snapshot tool already detects gaps
(missing forms, scope, photos). Until this tracker, those gaps just
showed up in the snapshot PDF — the team had to remember to chase
them. This module captures each gap at snapshot time as a tracked
item with:

  • Trello comment requesting it from the responsible tech (@mention)
  • Age (days since snapshot)
  • State: open / resolved / ignored
  • Per-job ignore flag with reason

Docusign-resend SLA lives here too: when the office resends docusign
paperwork, `record_docusign_resend` starts a 5-day timer. Past 5 days
without signature, the Hygiene panel flags it for front-desk
escalation ("send someone out for a physical signature").

Persistence:
    state["missing_items"]      = {request_id: entry}
    state["docusign_resends"]   = {request_id: entry}

Public API:
    capture_missing_items(client, *, card_id, missing, tech_initials="",
                           snapshot_at=None, post_comment=True)
        → returns list of created request_ids

    list_open_items(*, include_ignored=False, include_resolved=False)
        → newest-first list

    mark_resolved(request_id)
    mark_ignored(request_id, *, reason="")
    unignore(request_id)

    record_docusign_resend(client, *, card_id, post_comment=True)
        → request_id of new tracker

    list_docusign_resends(*, include_resolved=False)
    needs_physical_signature(*, threshold_days=5)
        → resends ≥ threshold days old still unsigned
    mark_docusign_signed(request_id)
    mark_physical_signature_done(request_id, *, note="")

The tech_initials → @mention map comes from the Tech Roster (so
re-mapping a tech's handle is centralized rather than baked in here).
"""
from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

import persistence as per

# Label canonicalization for missing-item types. Keys match the
# audit_logic check names so callers can pass raw form names through.
_ITEM_LABELS = {
    "atp":             "ATP form",
    "cif":             "CIF form",
    "cer":             "CER form",
    "cos":             "COS form",
    "scope":           "Scope",
    "sketch":          "Sketch",
    "initial_photos":  "Initial photos",
    "demo_photos":     "Demo photos",
    "final_photos":    "Final photos",
    "post_photos":     "Post photos",
}

# Default Trello comment templates. Caller can override per-call.
_DEFAULT_REQUEST_NOTE = (
    "📋 {source} identified missing item(s) for this job: {items}. "
    "{mention} please upload to the appropriate folder when possible. "
    "Tracked in Hygiene until resolved.")

# Display label for the {source} slot in the request note, keyed off
# `stage`. Initial Upload tags read "Initial Upload identified…" so the
# tech knows the office caught the gap at intake (not after the final
# snapshot).
_STAGE_SOURCE_LABEL = {
    "snapshot": "Snapshot",
    "initial":  "Initial Upload",
    "audit":    "Daily audit",
    "manual":   "Office",
}
_DEFAULT_REPEAT_NOTE = (
    "🔁 {nth} request for missing item(s): {items}. "
    "{tech_mention} please upload, {esc_mention} for visibility — "
    "previously requested {prev_dt}.")
_DEFAULT_DOCUSIGN_RESEND_NOTE = (
    "📝 Docusign paperwork resent — restarting 5-day signature timer.")
_DEFAULT_ESCALATION_NOTE = (
    "⚠ Docusign unsigned 5+ days after resend — escalating to front "
    "desk for a physical-signature visit.")

# Escalation @mentions used in repeat-request comments. When the same
# missing item is requested a 2nd+ time on different days, the repeat
# note tags these two so leadership has visibility. Configurable from
# the same Tech Roster as everyone else; falls back to literal handles
# below when the roster has no mapping.
_ESCALATION_INITIALS = ("ZAC", "SAM")

# Minimum time between two requests on the same (client, card, item)
# before the tracker counts it as a NEW request day. Prevents a quick
# re-run of the snapshot from inflating the count.
_REPEAT_COOLDOWN_HOURS = 12

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_IGNORED = "ignored"
STATUS_PENDING = "pending"          # docusign resend not yet signed
STATUS_SIGNED = "signed"            # docusign returned signed
STATUS_PHYSICAL_DONE = "physical_signature_done"

_TERMINAL_MISSING = {STATUS_RESOLVED, STATUS_IGNORED}
_TERMINAL_DOCUSIGN = {STATUS_SIGNED, STATUS_PHYSICAL_DONE, STATUS_IGNORED}


# ── Time helpers ────────────────────────────────────────────────────────

def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _iso(dt: _dt.datetime | None = None) -> str:
    return (dt or _utcnow()).replace(microsecond=0).isoformat()


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _days_since(iso_str: str) -> int:
    t = _parse_iso(iso_str)
    if not t:
        return 0
    return max(0, (_utcnow() - t).days)


# ── Persistence helpers ────────────────────────────────────────────────

def _load_missing() -> dict[str, dict[str, Any]]:
    raw = per.get("missing_items") or {}
    return raw if isinstance(raw, dict) else {}


def _save_missing(data: dict[str, dict[str, Any]]) -> None:
    per.set_value("missing_items", data)


def _load_resends() -> dict[str, dict[str, Any]]:
    raw = per.get("docusign_resends") or {}
    return raw if isinstance(raw, dict) else {}


def _save_resends(data: dict[str, dict[str, Any]]) -> None:
    per.set_value("docusign_resends", data)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _tech_handle(initials: str) -> str:
    """Resolve a tech-initials → @mention handle. Falls back to
    @<initials> when the roster doesn't have a Trello mapping."""
    s = (initials or "").strip()
    if not s:
        return ""
    try:
        import tech_roster as tr
        handle = tr.trello_handle_for(s)
        if handle:
            return handle if handle.startswith("@") else f"@{handle}"
    except Exception:
        pass
    return f"@{s}"


# ── Missing-items API ───────────────────────────────────────────────────

def _nth_word(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4+ → 'Nth' for the repeat-note ordinal."""
    if n == 1:
        return "1st"
    if n == 2:
        return "2nd"
    if n == 3:
        return "3rd"
    return f"{n}th"


def _hours_since(iso_str: str) -> float:
    t = _parse_iso(iso_str)
    if not t:
        return 1e9
    return (_utcnow() - t).total_seconds() / 3600.0


def capture_missing_items(client: str, *,
                            card_id: str = "",
                            card_url: str = "",
                            missing: list[str] | None = None,
                            tech_initials: str = "",
                            snapshot_at: str | None = None,
                            post_comment: bool = True,
                            stage: str = "snapshot",
                            note: str = "",
                            ) -> list[str]:
    """Record one tracked entry per missing item.

    `missing` is a list of canonical item keys (see `_ITEM_LABELS`)
    OR pre-labelled display strings. Unknown strings are kept as-is
    so callers can pass through audit-style labels.

    Per-day request counter:
      • Each call past the `_REPEAT_COOLDOWN_HOURS` window since the
        last Trello comment counts as a NEW request day.
      • `request_count` increments on each new request day.
      • The 2nd+ request day auto-tags the escalation handles
        (@zac, @sam) so leadership sees the recurring miss.

    Idempotent on (client, card_id, item_type) — re-capturing the same
    items on a re-snapshot within the cooldown window updates timestamps
    without bumping the counter or re-posting.

    Returns the list of request_ids touched.
    """
    items = [i for i in (missing or []) if i]
    if not client or not items:
        return []

    data = _load_missing()
    touched: list[str] = []
    newly_created_ids: list[str] = []
    repeat_request_ids: list[str] = []   # bumps to count this call
    now = _iso()
    snapshot_at = snapshot_at or now

    # Build a (canon_client, card_id, item_type) → existing-id index
    # so re-captures hit the same row.
    existing_index: dict[tuple, str] = {}
    for rid, rec in data.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") in _TERMINAL_MISSING:
            continue
        key = (
            (rec.get("client") or "").lower().strip(),
            rec.get("card_id") or "",
            rec.get("item_type") or "",
        )
        existing_index[key] = rid

    for item in items:
        item_type = item.lower().replace(" ", "_")
        label = _ITEM_LABELS.get(item_type, item)
        key = ((client or "").lower().strip(), card_id, item_type)
        rid = existing_index.get(key)
        if rid:
            rec = data[rid]
            rec["snapshot_at"] = snapshot_at
            rec["last_seen_at"] = now
            # New request DAY only if past the cooldown — protects
            # against quick re-snapshots inflating the count.
            last_posted = rec.get("trello_comment_posted_at") or ""
            if _hours_since(last_posted) >= _REPEAT_COOLDOWN_HOURS:
                repeat_request_ids.append(rid)
            touched.append(rid)
            continue
        rid = _new_id()
        rec = {
            "id":             rid,
            "client":         client,
            "card_id":        card_id,
            "card_url":       card_url,
            "item_type":      item_type,
            "item_label":     label,
            "created_at":     now,
            "snapshot_at":    snapshot_at,
            "last_seen_at":   now,
            "tech_initials":  tech_initials,
            "status":         STATUS_OPEN,
            "resolved_at":    None,
            "ignored_at":     None,
            "ignore_reason":  "",
            "trello_comment_posted_at": None,
            "request_count":  0,
            # Stage at which the gap was identified. Hygiene renders a
            # small chip ("INITIAL" / "SNAPSHOT" / "AUDIT") so the user
            # can tell whether the office caught it at intake or at
            # closeout.
            "stage":          (stage or "snapshot").lower(),
            # Optional free-text note the office added when manually
            # flagging the gap (e.g. "tech said sketch coming Monday").
            "note":           (note or "").strip(),
        }
        data[rid] = rec
        touched.append(rid)
        newly_created_ids.append(rid)

    _save_missing(data)

    # Best-effort Trello comments. Two paths:
    #
    #   1. Initial request comment for newly-tracked items. One Trello
    #      comment per call, listing every newly-created item, with
    #      the responsible tech @-mentioned.
    #
    #   2. Repeat-request comment for items already on the open list
    #      whose last comment was longer than _REPEAT_COOLDOWN_HOURS
    #      ago. One comment per call listing every repeat item, with
    #      the tech + the escalation handles (@zac, @sam) tagged.
    #      `request_count` increments on each repeat post so the
    #      "Nth request" text reflects history.
    if post_comment and card_id:
        try:
            import trello_client as tc
        except Exception:
            tc = None
        if tc is not None:
            stamp = _iso()
            tech_mention = _tech_handle(tech_initials)
            # Initial request — count starts at 1
            if newly_created_ids:
                try:
                    items_txt = ", ".join(
                        data[rid]["item_label"] for rid in newly_created_ids)
                    source_lbl = _STAGE_SOURCE_LABEL.get(
                        (stage or "snapshot").lower(), "Snapshot")
                    body = _DEFAULT_REQUEST_NOTE.format(
                        source=source_lbl,
                        items=items_txt,
                        mention=tech_mention or "Team —")
                    if note:
                        body += f"\n\nNote: {note}"
                    tc.post_comment(card_id, body)
                    for rid in newly_created_ids:
                        data[rid]["trello_comment_posted_at"] = stamp
                        data[rid]["request_count"] = 1
                except Exception:
                    pass
            # Repeat request — count bumps + escalation @mentions
            if repeat_request_ids:
                try:
                    items_txt = ", ".join(
                        data[rid]["item_label"] for rid in repeat_request_ids)
                    # Use the highest count among the batch's new
                    # count values so the ordinal reflects the worst
                    # offender on this card.
                    next_count = max(
                        (data[rid].get("request_count") or 0) + 1
                        for rid in repeat_request_ids)
                    prev_dt_iso = max(
                        (data[rid].get("trello_comment_posted_at") or "")
                        for rid in repeat_request_ids)
                    prev_dt_str = ""
                    try:
                        from datetime import datetime as _dt
                        prev_dt_str = _dt.fromisoformat(
                            prev_dt_iso.split(".")[0].rstrip("Z")
                        ).strftime("%a %b %d")
                    except Exception:
                        prev_dt_str = prev_dt_iso[:10]
                    esc = " ".join(_tech_handle(i) for i in _ESCALATION_INITIALS
                                    if _tech_handle(i))
                    tc.post_comment(card_id, _DEFAULT_REPEAT_NOTE.format(
                        nth=_nth_word(next_count),
                        items=items_txt,
                        tech_mention=tech_mention or "Team —",
                        esc_mention=esc or "@zac @sam",
                        prev_dt=prev_dt_str or "earlier"))
                    for rid in repeat_request_ids:
                        data[rid]["trello_comment_posted_at"] = stamp
                        data[rid]["request_count"] = (
                            (data[rid].get("request_count") or 0) + 1)
                except Exception:
                    pass
            _save_missing(data)

    return touched


def list_open_items(*, include_ignored: bool = False,
                      include_resolved: bool = False
                      ) -> list[dict]:
    """Every tracked missing-item row, newest-first by snapshot_at.
    Adds an `age_days` field for caller convenience."""
    rows: list[dict] = []
    for rid, rec in _load_missing().items():
        if not isinstance(rec, dict):
            continue
        st = rec.get("status") or STATUS_OPEN
        if st == STATUS_IGNORED and not include_ignored:
            continue
        if st == STATUS_RESOLVED and not include_resolved:
            continue
        out = dict(rec)
        out["age_days"] = _days_since(rec.get("snapshot_at", ""))
        rows.append(out)
    rows.sort(key=lambda r: r.get("snapshot_at") or "", reverse=True)
    return rows


def mark_resolved(request_id: str) -> dict | None:
    data = _load_missing()
    rec = data.get(request_id)
    if not isinstance(rec, dict):
        return None
    rec["status"] = STATUS_RESOLVED
    rec["resolved_at"] = _iso()
    _save_missing(data)
    return rec


def mark_ignored(request_id: str, *, reason: str = "") -> dict | None:
    data = _load_missing()
    rec = data.get(request_id)
    if not isinstance(rec, dict):
        return None
    rec["status"] = STATUS_IGNORED
    rec["ignored_at"] = _iso()
    rec["ignore_reason"] = reason or ""
    _save_missing(data)
    return rec


def unignore(request_id: str) -> dict | None:
    """Move an ignored row back to open. Reverse of mark_ignored."""
    data = _load_missing()
    rec = data.get(request_id)
    if not isinstance(rec, dict):
        return None
    if rec.get("status") != STATUS_IGNORED:
        return rec
    rec["status"] = STATUS_OPEN
    rec["ignored_at"] = None
    rec["ignore_reason"] = ""
    _save_missing(data)
    return rec


# ── Docusign resend SLA ─────────────────────────────────────────────────

def record_docusign_resend(client: str, *, card_id: str = "",
                            card_url: str = "",
                            post_comment: bool = True,
                            ) -> str | None:
    """Start the 5-day signature timer after the office resends
    docusign paperwork. Idempotent on `card_id` — re-recording on
    the same card restarts the timer (new resend = new clock)."""
    if not client:
        return None
    data = _load_resends()
    rid = None
    for existing_rid, rec in data.items():
        if (isinstance(rec, dict)
                and rec.get("card_id") == card_id
                and rec.get("status") not in _TERMINAL_DOCUSIGN):
            rid = existing_rid
            break
    now = _iso()
    if rid is None:
        rid = _new_id()
        data[rid] = {
            "id":            rid,
            "client":        client,
            "card_id":       card_id,
            "card_url":      card_url,
            "resent_at":     now,
            "status":        STATUS_PENDING,
            "escalation_posted_at": None,
            "signed_at":     None,
            "physical_signature_at": None,
        }
    else:
        # Restart the timer + clear any prior escalation flag.
        data[rid]["resent_at"] = now
        data[rid]["escalation_posted_at"] = None
        data[rid]["status"] = STATUS_PENDING

    _save_resends(data)

    if post_comment and card_id:
        try:
            import trello_client as tc
            tc.post_comment(card_id, _DEFAULT_DOCUSIGN_RESEND_NOTE)
        except Exception:
            pass

    return rid


def list_docusign_resends(*, include_resolved: bool = False
                            ) -> list[dict]:
    """Every resend row, newest-first by resent_at. `age_days` added."""
    rows: list[dict] = []
    for rid, rec in _load_resends().items():
        if not isinstance(rec, dict):
            continue
        if (not include_resolved
                and rec.get("status") in _TERMINAL_DOCUSIGN):
            continue
        out = dict(rec)
        out["age_days"] = _days_since(rec.get("resent_at", ""))
        rows.append(out)
    rows.sort(key=lambda r: r.get("resent_at") or "", reverse=True)
    return rows


def needs_physical_signature(*, threshold_days: int = 5
                                ) -> list[dict]:
    """Resends ≥ `threshold_days` old without a signature. Posts the
    escalation comment to the card on first detection so the front
    desk has a visible cue."""
    out = []
    data = _load_resends()
    changed = False
    for rid, rec in data.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") != STATUS_PENDING:
            continue
        age = _days_since(rec.get("resent_at", ""))
        if age < threshold_days:
            continue
        if not rec.get("escalation_posted_at") and rec.get("card_id"):
            try:
                import trello_client as tc
                tc.post_comment(rec["card_id"], _DEFAULT_ESCALATION_NOTE)
                rec["escalation_posted_at"] = _iso()
                changed = True
            except Exception:
                pass
        row = dict(rec)
        row["age_days"] = age
        out.append(row)
    if changed:
        _save_resends(data)
    return out


def mark_docusign_signed(request_id: str) -> dict | None:
    data = _load_resends()
    rec = data.get(request_id)
    if not isinstance(rec, dict):
        return None
    rec["status"] = STATUS_SIGNED
    rec["signed_at"] = _iso()
    _save_resends(data)
    return rec


def mark_physical_signature_done(request_id: str, *, note: str = ""
                                    ) -> dict | None:
    data = _load_resends()
    rec = data.get(request_id)
    if not isinstance(rec, dict):
        return None
    rec["status"] = STATUS_PHYSICAL_DONE
    rec["physical_signature_at"] = _iso()
    if note:
        rec["physical_signature_note"] = note
    _save_resends(data)
    return rec
