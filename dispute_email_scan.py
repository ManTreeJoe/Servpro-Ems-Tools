"""Inbox-source dispute detection.

Scans the local Outlook inbox for messages whose subject or body
matches the dispute-keyword regex. Each match → `dispute_tracker
.upsert_from_email(...)` (insert-if-missing semantics, so re-runs
don't stomp your tracker edits).

Intentionally separate from `xa_email_ingest` and `adjuster_monitor`:
those have different match/post semantics (XA-note correspondence
vs. inbound adjuster receipts). Disputes need a third axis — same
inbox, different keyword set, different downstream surface.

Keeps a `dispute_email_seen` persistence list so a re-scan over the
same days doesn't re-touch messages we already routed. (The tracker
itself dedupes by claim/insured, but seen-set is cheaper and
short-circuits the upsert-then-discard cycle.)
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import persistence as per


# ── Billing-dispute email parser ─────────────────────────────────────────
# Carriers send line-item audit reductions in a stock format:
#   "Line 4 please adjust to DMO DUMP ... (Net Reduction $751.05)"
#   "Total adjustments of $6,899.45 to original invoice amount of
#    $35,990.84 resulting in revised total of $29,091.39"
# parse_billing_dispute() turns that into a structured dispute payload so it
# can drop straight into the Dispute Tracker instead of being retyped.
_BD_LINE_RE = re.compile(
    r'Line\s+(\d+)\b(.*?)\(Net\s+Reduction[^\d$]*\$?\s*([\d,]+\.\d{2})\)',
    re.IGNORECASE | re.DOTALL)
_BD_ADJ_RE = re.compile(
    r'adjustment[s]?\s+of\s*\$?\s*([\d,]+\.\d{2})', re.IGNORECASE)
_BD_ORIG_RE = re.compile(
    r'original\s+invoice\s+amount\s+of\s*\$?\s*([\d,]+\.\d{2})', re.IGNORECASE)
_BD_REV_RE = re.compile(
    r'revised\s+total\s+of\s*\$?\s*([\d,]+\.\d{2})', re.IGNORECASE)
_BD_CLAIM_RE = re.compile(r'claim\s*#?\s*[:\-]?\s*(\d{6,}[-]?\d?)', re.IGNORECASE)


def _bd_money(s):
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def parse_billing_dispute(text):
    """Parse a carrier billing-dispute / audit-reduction email into a dispute
    payload. Returns None when it doesn't look like one (no line adjustments
    AND no totals). Otherwise:
        {"claim": str, "amount": str, "summary": str,
         "lines": [{"line": int, "reason": str, "reduction": float}, ...],
         "totals": {"adjustments"/"original"/"revised": float}}
    `amount` is the total disputed reduction (the adjustments figure, else the
    sum of the per-line reductions)."""
    t = text or ""
    lines = []
    for m in _BD_LINE_RE.finditer(t):
        reason = " ".join(m.group(2).split()).strip(" .;:>-»")
        reason = re.sub(r'^please\s+adjust\s+to\s+', "", reason, flags=re.I)
        lines.append({"line": int(m.group(1)),
                      "reason": reason,
                      "reduction": _bd_money(m.group(3))})
    totals = {}
    for key, rx in (("adjustments", _BD_ADJ_RE), ("original", _BD_ORIG_RE),
                    ("revised", _BD_REV_RE)):
        mm = rx.search(t)
        if mm:
            totals[key] = _bd_money(mm.group(1))
    if not lines and not totals:
        return None

    cm = _BD_CLAIM_RE.search(t)
    claim = cm.group(1) if cm else ""

    amount = totals.get("adjustments") or sum(l["reduction"] for l in lines)

    summ = [f"Line {l['line']}: {l['reason']} (−${l['reduction']:,.2f})"
            for l in lines]
    if totals:
        if summ:
            summ.append("")
        if "adjustments" in totals:
            summ.append(f"Total adjustments: ${totals['adjustments']:,.2f}")
        if "original" in totals:
            summ.append(f"Original invoice: ${totals['original']:,.2f}")
        if "revised" in totals:
            summ.append(f"Revised total: ${totals['revised']:,.2f}")

    return {
        "claim":   claim,
        "amount":  f"{amount:,.2f}" if amount else "",
        "summary": "\n".join(summ),
        "lines":   lines,
        "totals":  totals,
    }


# Subject/body phrases that flag a message as a dispute. Tuned from the
# real EMS@ inbox — claim-dispute language tends to cluster on a small
# set of stock phrasings ("disputing the audit", "audit dispute filed",
# "we contest", carrier-side rejection). Extend as new variants surface.
_DISPUTE_PATTERNS = re.compile(
    r"\b(?:"
    r"audit\s+dispute"                       # canonical phrasing
    r"|dispute(?:s|d|ing)?\s+(?:the|this|your|our)\s+audit"
    r"|disputing\s+(?:the|this|your|our)?"   # generic intent
    r"|contest(?:s|ed|ing)?\s+(?:the|this|your|our)?\s*(?:audit|estimate|finding)"
    r"|file(?:d|ing)?\s+(?:a|an)\s+dispute"
    r"|formal\s+dispute"
    r"|rebuttal\s+(?:to|of)\s+(?:the|this|your|our)?\s*audit"
    r"|reject(?:s|ed|ing)?\s+(?:the|this|your|our)?\s*(?:audit|estimate)"
    r")\b",
    re.IGNORECASE,
)


# Carrier domain → display name map, copied from adjuster_monitor so we
# can fill the Carrier column when the sender's domain matches a
# known carrier. Keeps this module standalone (no import cycle with
# adjuster_monitor which already pulls trello_client + persistence).
_CARRIER_DOMAINS: tuple[tuple[str, str], ...] = (
    ("statefarm",        "State Farm"),
    ("aaa",              "AAA"),
    ("mercury",          "Mercury"),
    ("farmers",          "Farmers"),
    ("usaa",             "USAA"),
    ("allstate",         "Allstate"),
    ("libertymutual",    "Liberty Mutual"),
    ("safeco",           "Safeco"),
    ("travelers",        "Travelers"),
    ("nationwide",       "Nationwide"),
    ("bamboo",           "Bamboo"),
    ("amfam",            "AmFam"),
    ("connectins",       "Connect"),
    ("californiacasualty", "California Casualty"),
    ("hartford",         "The Hartford"),
    ("chubb",            "Chubb"),
    ("metlife",          "MetLife"),
)


_CLAIM_RE = re.compile(r"\b\d{6,}[-]?\d?\b")


def _carrier_for(email: str) -> str:
    d = (email or "").split("@", 1)[-1].lower()
    if not d:
        return ""
    for marker, name in _CARRIER_DOMAINS:
        if marker in d:
            return name
    return ""


def _claim_numbers(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(0) for m in _CLAIM_RE.finditer(text)]


def _seen() -> set[str]:
    raw = per.get("dispute_email_seen") or []
    if not isinstance(raw, list):
        return set()
    return {s for s in raw if isinstance(s, str)}


def _remember_seen(message_ids: list[str]) -> None:
    if not message_ids:
        return
    cur = list(_seen())
    cur.extend(m for m in message_ids if m and m not in cur)
    # Bound the seen-set so it doesn't grow unboundedly. 5000 is ~2
    # years of inbox at typical volume — plenty for re-scan idempotency.
    if len(cur) > 5000:
        cur = cur[-5000:]
    per.set_value("dispute_email_seen", cur)


def scan_inbox(*, days: int = 14, top: int = 200,
                progress_cb=None) -> dict[str, Any]:
    """Pull recent inbox messages, regex for dispute language, push
    matches into the tracker. Returns:
        {"matched": [...], "new_in_tracker": N, "skipped_seen": N}

    Idempotent — re-running over the same window is cheap (seen-set
    short-circuits) and harmless (tracker upsert is insert-if-missing).
    """
    try:
        import outlook_local as ol
    except Exception:
        return {"matched": [], "new_in_tracker": 0, "skipped_seen": 0,
                "error": "outlook_local import failed"}

    since = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
              - _dt.timedelta(days=days))
    try:
        messages = ol.list_recent_messages(since=since, top=top)
    except Exception as ex:
        return {"matched": [], "new_in_tracker": 0, "skipped_seen": 0,
                "error": str(ex)}

    seen = _seen()
    matched: list[dict] = []
    skipped = 0
    new_in_tracker = 0
    total = len(messages)
    new_message_ids: list[str] = []

    # Lazy import here so a test environment without openpyxl
    # doesn't crash importing this module.
    import dispute_tracker as dt

    for i, m in enumerate(messages, start=1):
        if progress_cb:
            try:
                progress_cb(i, total, m.get("subject", "")[:60])
            except Exception:
                pass
        msg_id = m.get("id") or ""
        if msg_id and msg_id in seen:
            skipped += 1
            continue
        subject = (m.get("subject") or "").strip()
        preview = (m.get("bodyPreview") or "").strip()
        combined = f"{subject}\n{preview}"
        if not _DISPUTE_PATTERNS.search(combined):
            if msg_id:
                new_message_ids.append(msg_id)
            continue
        sender = ((m.get("from") or {}).get("emailAddress") or {})
        sender_addr = (sender.get("address") or "").lower()
        sender_name = (sender.get("name") or "").strip()
        # Try to extract a claim# from the message.
        claims = _claim_numbers(combined)
        claim = claims[0] if claims else ""
        carrier = _carrier_for(sender_addr)
        # Insured guess: pull from subject "Last, First - Carrier ..."
        # pattern. Falls back to sender name. Trello-card match comes
        # later when the user reviews the row.
        insured_guess = ""
        sub_match = re.match(
            r"^(?:re:|fw:|fwd:)?\s*"
            r"([A-Z][\w'\.-]+(?:\s*,\s*[\w'\.-]+|\s+[A-Z][\w'\.-]+))",
            subject, re.IGNORECASE)
        if sub_match:
            insured_guess = sub_match.group(1).strip()
        elif sender_name and "@" not in sender_name:
            insured_guess = sender_name
        was_new, row_no = dt.upsert_from_email(
            insured=insured_guess, claim=claim, carrier=carrier,
            subject=subject, preview=preview)
        if was_new:
            new_in_tracker += 1
        matched.append({
            "message_id":   msg_id,
            "subject":      subject,
            "from":         sender_addr,
            "sender_name":  sender_name,
            "received":     m.get("receivedDateTime", ""),
            "insured":      insured_guess,
            "claim":        claim,
            "carrier":      carrier,
            "was_new":      was_new,
            "tracker_row":  row_no,
        })
        if msg_id:
            new_message_ids.append(msg_id)

    _remember_seen(new_message_ids)
    return {"matched": matched,
            "new_in_tracker": new_in_tracker,
            "skipped_seen": skipped}


# CLI for ad-hoc rescan / debugging.
def _cli(argv):
    days = 14
    for a in argv:
        if a.startswith("--days="):
            try:
                days = int(a.split("=", 1)[1])
            except ValueError:
                pass
    result = scan_inbox(days=days)
    print(f"matched: {len(result.get('matched') or [])}")
    print(f"new in tracker: {result.get('new_in_tracker', 0)}")
    print(f"skipped (already seen): {result.get('skipped_seen', 0)}")
    if result.get("error"):
        print(f"error: {result['error']}")
        return 1
    for m in (result.get("matched") or [])[:20]:
        flag = "+" if m["was_new"] else " "
        print(f"  {flag} [{m['received'][:10]}] {m['subject'][:60]}")
        print(f"      from {m['from']} → insured={m['insured']!r} "
              f"claim={m['claim']!r} carrier={m['carrier']!r}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
