"""XactAnalysis inquiry detection → Inquiries & Disputes tracker.

Carrier adjusters post questions and action-requests as XA notes, which
Verisk auto-emails to the EMS@ inbox (donotreply@xactware.com). Most XA
notes are our own staff status updates ("Initial Inspection performed…"),
but a minority are genuine adjuster INQUIRIES we owe an answer:

    "Is any mitigation actually needed since it's just wet flooring?
     Also are you able to handle the repair portion?"

This module surfaces those as review-gated candidates (mirrors
adjuster_monitor's approval queue — NOTHING auto-writes). The user
approves a candidate from the Hygiene panel, which upserts it into the
Inquiries & Disputes tracker as an `Inquiry` row (intake = XA).

Parsing (Insured / Claim # / Note) reuses `xa_email_ingest`'s templated
notification parser — see that module for the regex set.

Persistence keys:
    xa_inquiry_pending    — list of candidate dicts awaiting approval
    xa_inquiry_dismissed  — message_ids the user dismissed (don't re-queue)
    xa_inquiry_approved   — message_ids already pushed to the tracker
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import persistence as per


# ── Inquiry detection ───────────────────────────────────────────────────────
# An XA note counts as an inquiry when it asks a question OR makes an action
# request directed at us. Multi-word request phrases (not a bare "please")
# keep our own staff status notes — which often contain "please note,…" —
# from false-matching.
_REQUEST_RE = re.compile(
    r"\b(?:"
    r"please\s+(?:provide|upload|send|confirm|advise|clarify|review|"
    r"complete|submit|forward|update)"
    r"|can\s+you|could\s+you|would\s+you|are\s+you\s+able|will\s+you\s+be"
    r"|do\s+you\s+need|do\s+we\s+need"
    r"|need\s+(?:you|us|the|a|an|your)\b"
    r"|let\s+(?:us|me)\s+know"
    r"|kindly|requesting|request\s+that|waiting\s+on"
    r")\b",
    re.IGNORECASE,
)


def is_inquiry_note(text: str) -> bool:
    """True when the note text reads as an adjuster question or action
    request (the 'questions + requests' signal the user picked)."""
    if not text or not text.strip():
        return False
    if "?" in text:
        return True
    return bool(_REQUEST_RE.search(text))


def _first_sentence(text: str, *, limit: int = 200) -> str:
    """A short preview for the candidate row — first question/sentence."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    # Prefer the first question if there is one.
    q = t.find("?")
    if 0 <= q < limit:
        return t[: q + 1]
    return t[:limit] + ("…" if len(t) > limit else "")


# ── Pending queue (mirrors adjuster_monitor._queue_pending shape) ────────────

def _as_list(key: str) -> list:
    raw = per.get(key) or []
    return raw if isinstance(raw, list) else []


def list_pending() -> list[dict]:
    """Candidate inquiries awaiting the user's approval."""
    return [e for e in _as_list("xa_inquiry_pending") if isinstance(e, dict)]


def _dismissed_ids() -> set[str]:
    return {s for s in _as_list("xa_inquiry_dismissed") if isinstance(s, str)}


def _approved_ids() -> set[str]:
    return {s for s in _as_list("xa_inquiry_approved") if isinstance(s, str)}


def _queue(entry: dict) -> None:
    mid = entry.get("message_id") or ""
    queue = [e for e in list_pending()
             if (e or {}).get("message_id") != mid]
    queue.append(entry)
    per.set_value("xa_inquiry_pending", queue)


def _drop_pending(message_id: str) -> dict | None:
    queue = list_pending()
    keep, dropped = [], None
    for e in queue:
        if (e or {}).get("message_id") == message_id and dropped is None:
            dropped = e
        else:
            keep.append(e)
    per.set_value("xa_inquiry_pending", keep)
    return dropped


def dismiss(message_id: str) -> bool:
    """✕ Don't track this one — drop from the queue and remember so a
    re-scan doesn't surface it again."""
    if not message_id:
        return False
    _drop_pending(message_id)
    dis = _dismissed_ids()
    dis.add(message_id)
    per.set_value("xa_inquiry_dismissed", sorted(dis)[-5000:])
    return True


def approve(message_id: str) -> dict:
    """✓ Add this inquiry to the Inquiries & Disputes tracker as an
    `Inquiry` row (intake = XA). Drops it from the queue and records the
    message_id so a re-scan won't re-queue it."""
    if not message_id:
        return {"ok": False, "error": "no message_id"}
    entry = _drop_pending(message_id)
    if entry is None:
        # Maybe already approved/dismissed — surface gracefully.
        return {"ok": False, "error": "not in pending queue"}
    try:
        import dispute_tracker as dt
        payload = {
            dt.COL_INSURED: entry.get("insured") or "",
            dt.COL_CLAIM:   entry.get("claim") or "",
            dt.COL_TYPE:    "Inquiry",
            dt.COL_SUMMARY: entry.get("note") or entry.get("preview") or "",
        }
        was_new, row = dt.upsert(payload, source="XA")
    except Exception as ex:
        # Re-queue so the candidate isn't lost on a failed write.
        _queue(entry)
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    appr = _approved_ids()
    appr.add(message_id)
    per.set_value("xa_inquiry_approved", sorted(appr)[-5000:])
    return {"ok": True, "was_new": was_new, "row": row}


# ── Scan ─────────────────────────────────────────────────────────────────────

def _open_claim_keys() -> set[str]:
    """Claim numbers already present in the tracker — so we don't queue
    an inquiry for a claim that's already being handled there."""
    try:
        import dispute_tracker as dt
        keys = set()
        for r in (dt.read_rows() or []):
            c = (r.get(dt.COL_CLAIM) or "").strip().lower()
            if c:
                keys.add(c)
        return keys
    except Exception:
        return set()


def scan(*, days: int = 30, top: int = 300, progress_cb=None) -> dict[str, Any]:
    """Walk the recent inbox, parse XA notification emails, queue the ones
    that read as adjuster inquiries (and aren't already tracked / dismissed
    / approved). Returns {queued, scanned, candidates, skipped}.

    Idempotent: re-running is cheap and won't double-queue (dedup by
    message_id + dismissed/approved sets + already-in-tracker claim)."""
    try:
        import outlook_local as ol
        import xa_email_ingest as xa
    except Exception as ex:
        return {"queued": 0, "scanned": 0, "candidates": [],
                "error": f"import failed: {ex}"}

    since = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
             - _dt.timedelta(days=days))
    try:
        messages = ol.list_recent_messages(since=since, top=top)
    except Exception as ex:
        return {"queued": 0, "scanned": 0, "candidates": [],
                "error": str(ex)}

    dismissed = _dismissed_ids()
    approved = _approved_ids()
    pending_ids = {e.get("message_id") for e in list_pending()}
    tracked_claims = _open_claim_keys()

    queued = 0
    candidates: list[dict] = []
    total = len(messages)
    for i, m in enumerate(messages, start=1):
        if progress_cb:
            try:
                progress_cb(i, total, (m.get("subject") or "")[:60])
            except Exception:
                pass
        if not xa.is_xa_notification(m):
            continue
        msg_id = m.get("id") or ""
        if not msg_id or msg_id in dismissed or msg_id in approved \
                or msg_id in pending_ids:
            continue
        subject = m.get("subject") or ""
        try:
            body = ol.get_message_body(msg_id) or m.get("bodyPreview") or ""
        except Exception:
            body = m.get("bodyPreview") or ""
        fields = xa.parse_xa_notification(subject, body)
        note = (fields.get("note") or "").strip()
        if not is_inquiry_note(note):
            continue
        claim = (fields.get("claim") or "").strip()
        if claim and claim.lower() in tracked_claims:
            continue  # already in the tracker — don't double-surface
        entry = {
            "message_id": msg_id,
            "insured":    (fields.get("insured") or "").strip(),
            "claim":      claim,
            "note":       note,
            "preview":    _first_sentence(note),
            "received":   m.get("receivedDateTime", ""),
            "subject":    subject,
            "queued_at":  _dt.datetime.now().isoformat(timespec="seconds"),
        }
        _queue(entry)
        pending_ids.add(msg_id)
        queued += 1
        candidates.append(entry)

    return {"queued": queued, "scanned": total,
            "candidates": candidates, "skipped": 0}


def _cli(argv):
    days = 30
    for a in argv:
        if a.startswith("--days="):
            try:
                days = int(a.split("=", 1)[1])
            except ValueError:
                pass
    res = scan(days=days)
    if res.get("error"):
        print("error:", res["error"])
        return 1
    print(f"scanned {res['scanned']} · queued {res['queued']} new inquiries")
    for c in res.get("candidates", [])[:30]:
        print(f"  [{(c['received'] or '')[:10]}] {c['insured']} "
              f"({c['claim']}): {c['preview']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
