"""Estimate Request SLA tracker.

Inbound inquiries from adjusters (email) or carriers (XA notes) become
EstimateRequests with a 48-hour SLA clock. The user clicks "Send 48h ack"
on the Hygiene panel to:

  1. Copy a canonical acknowledgment to clipboard (paste into XA)
  2. Open the source email link
  3. Post a Trello comment with the assigned estimator @mention
  4. Open a Teams DM to the estimator
  5. Start the 48h clock

After the 48h deadline, requests promote to 'overdue' on read. The user
can either Complete or Extend (with a reason + additional hours).

State lives in ``persistence.estimate_requests``. Excel mirroring lives
in ``estimate_requests_excel`` (best-effort — a locked file never blocks
the persistence write).

Public API:
    ACK_TEMPLATE                                  — canonical reply text
    compute_id(source, source_id, claim)          — stable per-request hash
    detect_pending(xa_groups, adjuster_result)    — fold scan outputs into store
    mark_acked(request_id)                        — start the 48h clock
    mark_completed(request_id, *, note='')        — done
    mark_extended(request_id, *, reason, extra_hours)
    dismiss(request_id, *, reason='')             — junk / dupe / not an inquiry
    pending_requests() / acked_waiting_requests() / overdue_requests()
    all_active()                                  — everything but Completed/Dismissed
"""
from __future__ import annotations

import datetime as _dt
import hashlib

import persistence as per


# Canonical acknowledgment the user pastes into XactAnalysis (or replies
# with via Outlook for non-XA adjusters). Two variants:
#
#   ACK_TEMPLATE      — file is already assigned to a specific estimator.
#                        The 48h clock is on that estimator.
#   TBA_ACK_TEMPLATE  — file is in the TBA (To-Be-Assigned) lane. We
#                        commit to assigning + responding within 48h
#                        but don't yet have an estimator's name to give.
#
# Pick via ack_template_for(record). Wording for the TBA variant is a
# best-faith default — update here when the user supplies their preferred
# phrasing.
ACK_TEMPLATE = (
    "Your inquiry has been received. "
    "Please allow our estimating team 48 hours to address."
)
TBA_ACK_TEMPLATE = (
    "Your inquiry has been received. "
    "We are assigning the file to an estimator and will follow up "
    "within 48 hours."
)

# Default SLA window. Kept as a module constant rather than a magic
# number so a future "set carrier-specific SLAs" feature has one place
# to override.
DEFAULT_SLA_HOURS = 48


# Lane → estimator routing. Mirrors the APA Monitor map at
# apa_monitor_gui.py:1630. Substring match against the lane name
# (lowercased), insertion order — longer / more specific keys come
# first so combo lanes route correctly. Keep in sync manually with the
# APA map; small enough that drift is easy to spot at review time.
_LANE_TO_ESTIMATOR = (
    # Combo lanes — must beat the bare names that come after
    ("juantes",          "JUAN"),
    ("kim+esteban",      "KIM"),
    ("samantha / al jr", "SAMANTHA"),
    ("samantha/al jr",   "SAMANTHA"),
    ("al jr",            "AARON L"),
    ("aaron l",          "AARON L"),
    # Single-estimator lanes
    ("juan",      "JUAN"),
    ("aaron",     "AARON"),
    ("johnny",    "JOHNNY"),
    ("kim",       "KIM"),
    ("zac",       "ZAC"),
    ("esteban",   "ESTEBAN"),
    ("victoria",  "VICTORIA"),
    ("pablo",     "PABLO"),
    ("samantha",  "SAMANTHA"),
    ("recon",     "RECON"),
)

# Lane substrings that mean "no estimator assigned yet". Match BEFORE
# the estimator map so a lane named "TBA — Aaron review" still routes
# to TBA.
_TBA_LANE_MARKERS = ("to be assigned", "estimating tba", "tba ", " tba",
                       "/ tba", "tba/", "unassigned", "(tba)",
                       "needs assignment", "pending assignment")


def classify_assignment(card_id: str) -> tuple[str, str]:
    """Look up the card's current Trello lane and return
    ``(status, estimator)`` where:

      status = "assigned"  — card is in a recognized estimator lane;
                              estimator is the name (e.g. "JUAN")
      status = "tba"       — card is in a TBA / Unassigned lane;
                              estimator is ""
      status = "unknown"   — no card_id, Trello lookup failed, or the
                              lane name didn't match anything; estimator
                              is "" — caller should treat as TBA for
                              ack purposes but may want to surface a
                              "lane not recognized" hint to the user

    Live lookup (one tc.get_card + one tc.get_list call). Wrapped in
    try/except so a Trello outage degrades to ("unknown", "") rather
    than blocking the ack flow.
    """
    if not (card_id or "").strip():
        return ("unknown", "")
    try:
        import trello_client as tc
        card = tc.get_card(card_id)
        if not card:
            return ("unknown", "")
        list_id = (card.get("idList") or "").strip()
        lst = tc.get_list(list_id) if list_id else None
        lane_name = ((lst or {}).get("name") or "").strip()
    except Exception:
        return ("unknown", "")
    if not lane_name:
        return ("unknown", "")
    needle = lane_name.lower()
    if any(m in needle for m in _TBA_LANE_MARKERS):
        return ("tba", "")
    # The "tba" word can appear inside a lane like "Estimating TBA" —
    # _TBA_LANE_MARKERS already handles that. A bare "tba" lane is
    # also TBA: match on word boundary.
    if needle.strip() == "tba":
        return ("tba", "")
    for marker, estimator in _LANE_TO_ESTIMATOR:
        if marker in needle:
            return ("assigned", estimator)
    return ("unknown", "")


def ack_template_for(status: str) -> str:
    """Pick the canonical reply text for an assignment status.

    "assigned" / "unknown"  → ACK_TEMPLATE
        "unknown" covers post-assignment lanes (WORK IN PROGRESS,
        TEST/CLEARANCE, etc.) — the estimating team has the file,
        the lane just isn't one of the per-estimator buckets.
    "tba"                    → TBA_ACK_TEMPLATE
        Only fired when the card is sitting in a To-Be-Assigned lane,
        i.e. the file genuinely hasn't been routed to anyone yet.
    """
    if status == "tba":
        return TBA_ACK_TEMPLATE
    return ACK_TEMPLATE


# Status state machine. Stored as a string field on each request:
#   pending_ack → acked → (overdue promoted at read time) → completed
#                                            └→ extended → ...
#   any state → dismissed (terminal; user said "not a real inquiry")
STATUS_PENDING_ACK = "pending_ack"
STATUS_ACKED       = "acked"
STATUS_OVERDUE     = "overdue"   # synthesized at read-time, never stored
STATUS_COMPLETED   = "completed"
STATUS_DISMISSED   = "dismissed"

# Terminal states — never re-surface in the Hygiene panel.
_TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_DISMISSED)


# ── Time helpers ────────────────────────────────────────────────────────

def _now() -> _dt.datetime:
    """UTC now, naive (stripped tzinfo). Matches the convention used by
    persistence.set_hygiene_scan_cache so timestamps round-trip cleanly."""
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _iso(dt: _dt.datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat(timespec="seconds")


def _parse_iso(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


# ── ID hashing ──────────────────────────────────────────────────────────

def compute_id(source: str, source_id: str, claim: str = "") -> str:
    """Stable 12-char hex hash of (source, source_id, claim). Allows the
    detector to be re-run safely — the same email always produces the
    same request_id so re-scans dedupe instead of duplicating."""
    raw = f"{source}|{source_id}|{(claim or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ── Record construction ─────────────────────────────────────────────────

def _build_record(*, source: str, source_id: str, source_link: str,
                  claim: str, insured: str, carrier: str, adjuster: str,
                  card_id: str = "", card_url: str = "", card_name: str = "",
                  received_at: _dt.datetime | None = None,
                  uses_xa: bool = True,
                  is_explicit_request: bool = False) -> dict:
    """Build a fresh request record. Status starts at pending_ack and
    the deadline is set to received_at + SLA. The deadline gets reset on
    mark_acked so the 48-hour clock truly begins when the user acks.

    `is_explicit_request`: True when the source email body matches
    `adjuster_monitor._EXPLICIT_REQUEST_PATTERNS` ("please send the
    estimate", "where's the estimate", etc.). Renders as a 🔴 chip and
    sorts to the top of the section."""
    rid = compute_id(source, source_id, claim)
    rec_at = received_at or _now()
    deadline = rec_at + _dt.timedelta(hours=DEFAULT_SLA_HOURS)
    return {
        "request_id":   rid,
        "source":       source,
        "source_id":    source_id,
        "source_link":  source_link,
        "card_id":      card_id,
        "card_url":     card_url,
        "card_name":    card_name,
        "claim":        (claim or "").strip(),
        "insured":      (insured or "").strip(),
        "carrier":      (carrier or "").strip(),
        "adjuster":     (adjuster or "").strip(),
        "estimator":    "",                # resolved at ack time
        "uses_xa":      bool(uses_xa),
        "received_at":  _iso(rec_at),
        "acked_at":     None,
        "deadline":     _iso(deadline),
        "completed_at": None,
        "completed_note": "",
        "extensions":   [],
        "status":       STATUS_PENDING_ACK,
        "last_seen_at": _iso(rec_at),      # bumped on re-detect; useful for "fresh email on a stale inquiry"
        "dismiss_reason": "",
        "is_explicit_request": bool(is_explicit_request),
    }


def _register_if_new(record: dict) -> tuple[dict, bool]:
    """Upsert into persistence. If the request already exists, just bump
    last_seen_at (and refresh card_id / source_link if we have fresher
    values — adjuster-monitor sometimes resolves a card on a second pass
    that wasn't matched the first time). Returns (final_record, is_new)."""
    rid = record["request_id"]
    existing = per.get_estimate_request(rid)
    if existing is None:
        per.set_estimate_request(rid, record)
        return record, True
    # Bump last_seen and fill in any blanks the existing record was
    # missing. Don't touch status / acked_at / completed_at / extensions.
    existing["last_seen_at"] = _iso(_now())
    for k in ("card_id", "card_url", "card_name", "claim", "insured",
              "carrier", "adjuster", "source_link"):
        if not (existing.get(k) or "").strip() and (record.get(k) or "").strip():
            existing[k] = record[k]
    # Explicit-request flag is one-way upgrade: once a card has been
    # flagged as an explicit estimate request, it stays flagged even
    # if a later non-request email arrives on the same record. Never
    # downgrade — the original request still needs the priority treatment.
    if record.get("is_explicit_request") and not existing.get(
            "is_explicit_request"):
        existing["is_explicit_request"] = True
    per.set_estimate_request(rid, existing)
    return existing, False


# ── Detection ───────────────────────────────────────────────────────────

def detect_pending(xa_groups: list[dict] | None = None,
                    adjuster_result: dict | None = None) -> dict:
    """Fold scan outputs into the persistent store. Returns a summary:
        {"new": int, "updated": int, "active": [records]}

    Active = anything not Completed and not Dismissed (i.e. everything
    the Hygiene panel will render). Overdue rows are synthesized here by
    flipping status='overdue' on records past deadline (in-memory only —
    the stored status stays 'acked' so a manual deadline extension can
    un-overdue them cleanly).
    """
    new_count = 0
    upd_count = 0

    # Lazy import — keeps `estimate_requests` cheaply importable from
    # places that don't actually invoke detect_pending.
    try:
        from adjuster_monitor import is_explicit_estimate_request
    except Exception:
        def is_explicit_estimate_request(_t):
            return False

    # XA-source: only register groups whose note text explicitly asks
    # for an estimate. The pre-2026-05-14 "every XA note is an inquiry"
    # behavior buried real requests under dozens of routine status
    # updates / approvals; this restores signal-to-noise.
    for g in (xa_groups or []):
        msg_id = (g.get("source_msg_id") or g.get("msg_id") or "")
        link = (g.get("email_link") or g.get("webLink") or "")
        claim = (g.get("claim") or g.get("claim_number") or "")
        insured = (g.get("insured") or g.get("insured_hint") or "")
        carrier = (g.get("carrier") or "")
        adjuster = (g.get("adjuster") or g.get("sender_name") or "")
        card = (g.get("card") or {})
        received = _parse_iso(g.get("first_seen") or g.get("received") or "")
        # Aggregate every note body in the group + the carrier subject
        # if present; one match anywhere is enough.
        text_chunks = []
        for n in (g.get("notes") or []):
            if isinstance(n, dict):
                text_chunks.append(n.get("body") or "")
                text_chunks.append(n.get("subject") or "")
        for k in ("subject", "preview", "body"):
            v = g.get(k)
            if isinstance(v, str):
                text_chunks.append(v)
        combined = "\n".join(t for t in text_chunks if t)
        if not is_explicit_estimate_request(combined):
            continue
        rec = _build_record(
            source="xa",
            source_id=msg_id or f"xa-{claim or insured}",
            source_link=link,
            claim=claim, insured=insured,
            carrier=carrier, adjuster=adjuster,
            card_id=card.get("card_id") or card.get("id") or "",
            card_url=card.get("url") or card.get("shortUrl") or "",
            card_name=card.get("name") or "",
            received_at=received,
            uses_xa=True,
            is_explicit_request=True)
        _, is_new = _register_if_new(rec)
        new_count += int(is_new)
        upd_count += int(not is_new)

    # Email-source: only register when the message body / subject
    # explicitly asks for an estimate. `entry["explicit_request"]` is
    # set upstream by adjuster_monitor.is_explicit_estimate_request and
    # is the same gate is_explicit_estimate_request enforces here.
    # Routine status updates, approvals, scheduling chatter, and
    # promotional senders are dropped without creating a record.
    for entry in (adjuster_result or {}).get("posted", []):
        if not entry.get("explicit_request"):
            continue
        rec = _build_record(
            source="adjuster_email",
            source_id=entry.get("message_id", ""),
            source_link=entry.get("email_link", "") or entry.get("webLink", ""),
            claim=entry.get("claim", ""),
            insured=entry.get("card_name", "").split(" - ")[0],
            carrier=entry.get("carrier", ""),
            adjuster=entry.get("from", "") or entry.get("sender_name", ""),
            card_id=entry.get("card_id", ""),
            card_url=entry.get("card_url", ""),
            card_name=entry.get("card_name", ""),
            received_at=_parse_iso(entry.get("received", "")),
            uses_xa=False,                # we'll let the user mark XA on a per-card basis later
            is_explicit_request=True,
        )
        _, is_new = _register_if_new(rec)
        new_count += int(is_new)
        upd_count += int(not is_new)
    for entry in (adjuster_result or {}).get("unmatched", []):
        if not entry.get("explicit_request"):
            continue
        rec = _build_record(
            source="adjuster_email",
            source_id=entry.get("message_id", ""),
            source_link=entry.get("email_link", "") or entry.get("webLink", ""),
            claim="",
            insured="",
            carrier="",
            adjuster=entry.get("from", ""),
            received_at=_parse_iso(entry.get("received", "")),
            uses_xa=False,
            is_explicit_request=True)
        # Stash the raw subject so the UI can show "From X — <subject>"
        rec["email_subject"] = entry.get("subject", "")
        _, is_new = _register_if_new(rec)
        new_count += int(is_new)
        upd_count += int(not is_new)

    return {
        "new": new_count,
        "updated": upd_count,
        "active": all_active(),
    }


def purge_non_explicit() -> int:
    """Drop active records that were registered under the pre-2026-05-14
    broad-trigger rule and don't reflect an actual estimate request.

    Email-source records carry the explicit flag — keep only ones where
    `is_explicit_request=True`. XA-source records pre-filter had no
    flag at all (every group registered), so we conservatively drop
    every XA-source row; the next scan re-registers only ones whose
    note bodies pass the explicit gate.

    Returns the count of records dismissed (status set to 'dismissed'
    with reason='not_explicit_request_cleanup' so it's auditable and
    re-runnable safely).
    """
    purged = 0
    for rid, rec in list(per.iter_estimate_requests()):
        if not isinstance(rec, dict):
            continue
        if rec.get("status") in _TERMINAL_STATUSES:
            continue
        src = rec.get("source") or ""
        if src == "adjuster_email" and rec.get("is_explicit_request"):
            continue   # legitimate, keep
        # Drop — either email-source without explicit flag, or XA-source
        # registered before the gate existed.
        rec["status"] = STATUS_DISMISSED
        rec["dismiss_reason"] = "not_explicit_request_cleanup"
        per.set_estimate_request(rid, rec)
        purged += 1
    return purged


# ── Read-side views ─────────────────────────────────────────────────────

def _hydrate(rec: dict) -> dict:
    """Promote 'acked' → 'overdue' in-memory when deadline has passed.
    Always returns a shallow copy so callers can't mutate the store."""
    out = dict(rec)
    if out.get("status") == STATUS_ACKED:
        deadline = _parse_iso(out.get("deadline"))
        if deadline is not None and deadline < _now():
            out["status"] = STATUS_OVERDUE
    return out


def all_active() -> list[dict]:
    """Every non-terminal request, newest first."""
    rows = []
    for rid, rec in per.iter_estimate_requests():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") in _TERMINAL_STATUSES:
            continue
        rows.append(_hydrate(rec))
    rows.sort(key=lambda r: r.get("received_at") or "", reverse=True)
    return rows


def pending_requests() -> list[dict]:
    return [r for r in all_active() if r.get("status") == STATUS_PENDING_ACK]


def acked_waiting_requests() -> list[dict]:
    return [r for r in all_active() if r.get("status") == STATUS_ACKED]


def overdue_requests() -> list[dict]:
    return [r for r in all_active() if r.get("status") == STATUS_OVERDUE]


# ── Mutators ────────────────────────────────────────────────────────────

def mark_acked(request_id: str, *, estimator: str = "") -> dict | None:
    """Stamp acked_at = now, recompute deadline = now + SLA. Records the
    estimator name (so the row can render the @mention even if the user
    later changes the mapping). Returns the updated record or None if
    the request isn't found / already in a terminal state."""
    rec = per.get_estimate_request(request_id)
    if rec is None or rec.get("status") in _TERMINAL_STATUSES:
        return None
    now = _now()
    rec["acked_at"] = _iso(now)
    rec["deadline"] = _iso(now + _dt.timedelta(hours=DEFAULT_SLA_HOURS))
    rec["status"] = STATUS_ACKED
    if estimator:
        rec["estimator"] = estimator
    per.set_estimate_request(request_id, rec)
    _excel_sync_safe(rec)
    return rec


def mark_completed(request_id: str, *, note: str = "") -> dict | None:
    rec = per.get_estimate_request(request_id)
    if rec is None or rec.get("status") in _TERMINAL_STATUSES:
        return None
    rec["completed_at"] = _iso(_now())
    rec["completed_note"] = (note or "").strip()
    rec["status"] = STATUS_COMPLETED
    per.set_estimate_request(request_id, rec)
    _excel_sync_safe(rec)
    return rec


def mark_extended(request_id: str, *, reason: str,
                   extra_hours: int) -> dict | None:
    """Push deadline forward by `extra_hours` and record the reason. If
    the request is still pending_ack (no ack yet), the extension still
    applies — the deadline math is based on the current deadline value,
    not on acked_at, so a pre-ack extension is meaningful too."""
    if extra_hours <= 0:
        return None
    rec = per.get_estimate_request(request_id)
    if rec is None or rec.get("status") in _TERMINAL_STATUSES:
        return None
    current_deadline = _parse_iso(rec.get("deadline")) or _now()
    new_deadline = current_deadline + _dt.timedelta(hours=extra_hours)
    rec["deadline"] = _iso(new_deadline)
    rec.setdefault("extensions", []).append({
        "reason": (reason or "").strip(),
        "hours":  int(extra_hours),
        "at":     _iso(_now()),
    })
    # If the row was promoted to overdue at read-time and the new deadline
    # is in the future, the next _hydrate() call will reclassify it as
    # acked — no stored status flip needed.
    per.set_estimate_request(request_id, rec)
    _excel_sync_safe(rec)
    return rec


def dismiss(request_id: str, *, reason: str = "") -> dict | None:
    rec = per.get_estimate_request(request_id)
    if rec is None:
        return None
    rec["status"] = STATUS_DISMISSED
    rec["dismiss_reason"] = (reason or "").strip()
    per.set_estimate_request(request_id, rec)
    _excel_sync_safe(rec)
    return rec


# ── Excel sync (best-effort, never raises) ──────────────────────────────

def _excel_sync_safe(rec: dict) -> None:
    """Push the request to the Excel workbook. Wrapped in try/except so
    a locked file or unreachable share never blocks persistence writes."""
    try:
        import estimate_requests_excel
        estimate_requests_excel.sync_request(rec)
    except Exception:
        # Silent — the workbook is non-authoritative and will catch up
        # on the next sync_request that successfully grabs the file.
        pass


# ── CLI (smoke / debug) ─────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python estimate_requests.py list [--all]")
        print("  python estimate_requests.py show <request_id>")
        print("  python estimate_requests.py dismiss <request_id> [reason...]")
        return 1
    cmd = argv[0]
    if cmd == "list":
        show_all = "--all" in argv[1:]
        rows = (all_active() if not show_all
                else [_hydrate(r) for _, r in per.iter_estimate_requests()])
        if not rows:
            print("(none)")
            return 0
        for r in rows:
            print(f"  [{r['status']:11s}]  {r['claim']:14s}  "
                  f"{r['insured'][:30]:30s}  due {r['deadline']}")
        return 0
    if cmd == "show":
        if len(argv) < 2:
            print("show: missing request_id")
            return 2
        rec = per.get_estimate_request(argv[1])
        if rec is None:
            print("(not found)")
            return 1
        import json
        print(json.dumps(_hydrate(rec), indent=2))
        return 0
    if cmd == "dismiss":
        if len(argv) < 2:
            print("dismiss: missing request_id")
            return 2
        reason = " ".join(argv[2:])
        rec = dismiss(argv[1], reason=reason)
        print("(not found)" if rec is None else f"dismissed: {rec['request_id']}")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
