"""XactAnalysis-note ingest from Outlook.

XA has no public API. But every XA note staff posts is auto-emailed to
the carrier with EMS@servpro10100.com cc'd, so the EMS@ inbox holds a
chronological copy of every human-typed XA note.

This module reads that inbox, filters to the staff-→-carrier pattern,
groups emails by claim# / insured name, converts each email into a
synthetic note dict, and feeds the per-job lists through
`xa_notes.analyze_notes()` to surface stale jobs and open verbal
commitments.

Heavy work happens in `scan_inbox()`:
    1. `outlook_local.list_recent_messages` pulls the last N days of mail.
    2. Each message is checked against `is_xa_note_email` (sender is
       internal staff, recipient is a known carrier domain).
    3. Full bodies are fetched for matches and cached in persistence
       (`xa_email_bodies`) so re-runs cost nothing.
    4. Claim# is extracted from subject/body; emails are grouped.
    5. Each group's note list is fed to `xa_notes.analyze_notes`.
    6. Groups with `is_stale=True` OR open commitments are returned.

Trello card matching is best-effort: we search for a card whose desc
contains the claim#. When a match is found the gap row links straight
to the card; otherwise the row shows just the claim# / insured name and
the user can open the related email manually.

CLI:
    python xa_email_ingest.py preview [--days=60] [--top=400]
        Dump scanned emails + per-claim gap analysis without GUI.
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from typing import Any

import persistence as per
import xa_notes


# ── Constants ──────────────────────────────────────────────────────────────

# Carrier-recipient detection. Reuses adjuster_monitor's carrier list.
_CARRIER_DOMAIN_HINTS: tuple[str, ...] = (
    "statefarm", "aaa", "mercury", "farmers", "usaa", "allstate",
    "libertymutual", "safeco", "aegis", "travelers", "nationwide",
    "bamboo", "amfam", "connectins", "californiacasualty", "chartis",
    "hartford", "chubb", "metlife", "freedommortgage",
)
# Internal domains we don't treat as carrier-side recipients.
_INTERNAL_DOMAINS: tuple[str, ...] = (
    "servpro10100.com", "servpronet.com",
)
# Claim numbers vary by carrier — State Farm is something like
# "7596X260K", AAA might be "12-1234567-89", Mercury all-digits. We try a
# few common shapes and fall back to "any 8+-char alnum-with-dashes
# token".
_CLAIM_PATTERNS: tuple[re.Pattern, ...] = (
    # State Farm: 4 digit + letter + 3 digit + letter (e.g. 7596X260K)
    re.compile(r"\b\d{4}[A-Z]\d{3}[A-Z]\b"),
    # AAA / dash-style: digits-digits-digits
    re.compile(r"\b\d{2,3}-\d{4,8}-?\d{0,4}\b"),
    # Generic 6+ digit run (Mercury, Farmers, etc.).
    re.compile(r"\b\d{6,}\b"),
)
# Subject markers we use to recognize an XA note even when the claim# is
# missing. "Re: <Insured Name>" or just the insured name with carrier
# in the body is the soft signal.
_SUBJECT_NOISE_RE = re.compile(
    r"^(?:Re|Fwd|FW|RE|FYI):\s*", re.IGNORECASE)

# How many days of inbox to walk by default. XA work cycles run weeks to
# months; 60 days keeps the scan responsive while catching most open
# commitments.
DEFAULT_DAYS_BACK = 60
# Cap on Graph $top per page. Graph's documented limit is 1000 but
# practical perf falls off fast above 200 — we paginate cheaply via
# multiple list_recent_messages calls if needed in a future iteration.
DEFAULT_MAX_MESSAGES = 400

# Default "stale" threshold for analyze_notes — XA note silence beyond
# this on an active job is the flag.
STALE_DAYS = 5


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _domain(addr: str) -> str:
    if not addr or "@" not in addr:
        return ""
    return addr.split("@", 1)[1].strip().lower()


def _is_internal(addr: str) -> bool:
    d = _domain(addr)
    return any(marker in d for marker in _INTERNAL_DOMAINS)


def _is_carrier(addr: str) -> bool:
    d = _domain(addr)
    if not d:
        return False
    if any(marker in d for marker in _INTERNAL_DOMAINS):
        return False
    return any(marker in d for marker in _CARRIER_DOMAIN_HINTS)


# ── XA-pattern detection ───────────────────────────────────────────────────

_XA_NOTIFICATION_SENDERS: tuple[str, ...] = (
    "donotreply@xactware.com",
    "noreply@xactware.com",
    "donotreply@xactanalysis.com",
    "noreply@xactanalysis.com",
    "donotreply@verisk.com",
    "noreply@verisk.com",
)


def is_xa_notification(message: dict) -> bool:
    """True when the message is an automated XA notification email
    (sender is `donotreply@xactware.com` and similar). These carry the
    note text in the body verbatim ("An assignment note was added… /
    Insured: <name> / Claim #: <#> / Note: <text>") and are sent to
    everyone on the file — adjuster + EMS@ + other staff."""
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    addr = (sender.get("address") or "").lower().strip()
    if not addr:
        return False
    return addr in _XA_NOTIFICATION_SENDERS


def is_xa_note_email(message: dict) -> bool:
    """True when the message looks like an XA note — either:

      (a) Staff-→-carrier outbound note CC'd to EMS@:
          - Sender is internal AND not the EMS@ shared mailbox itself
          - At least one To recipient is a known carrier domain

      (b) Inbound XA notification email from `donotreply@xactware.com`
          (covers carrier-posted notes that ask us to do things — the
          user expects these to show up in the Hygiene XA section so
          they don't get lost).
    """
    if is_xa_notification(message):
        return True
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    sender_addr = (sender.get("address") or "").lower()
    if not _is_internal(sender_addr):
        return False
    if sender_addr.startswith("ems@"):
        return False
    to_list = message.get("toRecipients") or []
    for r in to_list:
        addr = ((r.get("emailAddress") or {}).get("address") or "").lower()
        if _is_carrier(addr):
            return True
    return False


# XA notification body template — Verisk emits this verbatim with
# `Insured:` / `Claim #:` / `Note:` keys on their own lines.
_NOTIF_INSURED_RE = re.compile(
    r"^\s*Insured:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_NOTIF_CLAIM_RE = re.compile(
    r"^\s*Claim\s*#?\s*:\s*(\S.*?)\s*$", re.MULTILINE | re.IGNORECASE)
# "Note:" header line, followed by the actual note body until the
# "To view the detailed information click on the following link" footer
# (or the true end of the body).
#
# IMPORTANT: terminate on the footer / dashed separator / END-OF-STRING
# (\Z), NOT `$`. With re.MULTILINE, `$` matches the end of the FIRST
# line, so a note that opens with a greeting on its own line ("Good
# Morning,\n\nIs mitigation needed…") was being truncated to just the
# greeting — the actual question was silently dropped. `\Z` + DOTALL
# lets the capture span every line of the note.
_NOTIF_NOTE_RE = re.compile(
    r"^[ \t]*Note:[ \t]*\r?\n(.*?)\s*"
    r"(?:\r?\n[ \t]*To view the detailed information"
    r"|\r?\n[ \t]*-{20,}"
    r"|\Z)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE)


def parse_xa_notification(subject: str, body: str) -> dict:
    """Extract the templated fields from a `donotreply@xactware.com`
    notification email. Returns:
        {"insured": str, "claim": str, "note": str}
    Any field can be empty when the body doesn't match the template.

    The note body is the human-typed text — what we actually want to
    surface in the Hygiene XA section. Subject acts as a fallback for
    insured when the body lacks the Insured: line."""
    out = {"insured": "", "claim": "", "note": ""}
    if not body:
        return out
    m = _NOTIF_INSURED_RE.search(body)
    if m:
        out["insured"] = m.group(1).strip()
    m = _NOTIF_CLAIM_RE.search(body)
    if m:
        out["claim"] = m.group(1).strip()
    m = _NOTIF_NOTE_RE.search(body)
    if m:
        # Trim trailing whitespace and any stray "-" sign-off lines.
        note_text = m.group(1).strip()
        note_text = re.sub(r"\n\s*-\s*$", "", note_text).strip()
        out["note"] = note_text
    # Fallback: pull insured from subject pattern
    # "An Assignment Note Has Been Added in XactAnalysis Insured: <NAME>"
    if not out["insured"] and subject:
        sm = re.search(r"Insured:\s*(.+?)\s*$", subject, re.IGNORECASE)
        if sm:
            out["insured"] = sm.group(1).strip()
    return out


def extract_claim_number(text: str) -> str:
    """First claim-number-shaped token found in `text`, or ''."""
    if not text:
        return ""
    for pattern in _CLAIM_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return ""


def extract_insured_hint(subject: str) -> str:
    """Cheap heuristic: when the subject is "Last, First - claim - topic"
    return the "Last, First" segment so we have something human-readable
    to display when the claim# is missing. Returns "" if the subject
    doesn't look like that template."""
    if not subject:
        return ""
    # Strip leading Re:/Fwd:
    s = _SUBJECT_NOISE_RE.sub("", subject).strip()
    # Take the part before the first " - " separator.
    parts = re.split(r"\s+-\s+", s, maxsplit=1)
    head = parts[0].strip()
    # Insured names usually contain a comma ("Main, Elizabeth") or two
    # capitalized words ("Elizabeth Main"). Keep short, drop if it looks
    # like a claim# instead.
    if len(head) < 3 or len(head) > 60:
        return ""
    if any(c.isdigit() for c in head):
        return ""
    return head


# ── Body cache ─────────────────────────────────────────────────────────────
# Re-fetching message bodies on every scan is wasteful — Graph charges a
# round-trip per message id. We cache by msg_id in persistence so re-runs
# are essentially free for already-seen mail.

def _body_cache() -> dict[str, str]:
    raw = per.get("xa_email_bodies") or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _save_body_cache(cache: dict[str, str]) -> None:
    per.set_value("xa_email_bodies", cache)


def _get_body(message_id: str, *, cache: dict[str, str]) -> str:
    if not message_id:
        return ""
    if message_id in cache:
        return cache[message_id]
    try:
        import outlook_local as ol
        body = ol.get_message_body(message_id) or ""
    except Exception:
        body = ""
    cache[message_id] = body
    return body


# ── Email → synthetic XA note ──────────────────────────────────────────────

def email_to_synthetic_note(message: dict, body: str) -> dict[str, Any]:
    """Convert a Graph message + body into the shape `xa_notes.analyze_notes`
    consumes (matches `parse_xa_notes` output)."""
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    received_iso = (message.get("receivedDateTime") or "")
    ts = _parse_iso(received_iso)
    return {
        "number":     None,
        "author":     (sender.get("name") or "").strip(),
        "email":      (sender.get("address") or "").strip(),
        "franchise":  "",
        "body":       (body or "").strip(),
        "timestamp":  ts,
        "kind":       "note",
        "is_system":  False,
        "_email_id":  message.get("id", ""),
        "_email_link": message.get("webLink", ""),
        "_email_subject": message.get("subject", ""),
    }


# ── Scan & analyze ─────────────────────────────────────────────────────────

def scan_inbox(*, days: int = DEFAULT_DAYS_BACK,
               top: int = DEFAULT_MAX_MESSAGES,
               progress_cb=None) -> dict[str, Any]:
    """Walk recent inbox messages, filter to XA notes, group by claim#
    (or insured-name fallback), build synthetic note lists, run gap
    analysis per group.

    Returns:
        {
          "groups": [
              {
                "claim":           "<claim# or '' fallback>",
                "insured_hint":    "<best-guess insured name>",
                "notes":           [synthetic_note, ...] (newest-first),
                "analysis":        <result of xa_notes.analyze_notes>,
                "card":            None | <Trello card dict>,
              },
              ...
          ],
          "scanned":   int,    # how many messages we walked
          "matched":   int,    # how many were XA-pattern emails
          "unrouted":  [{...}, ...],   # XA emails with no claim# extracted
        }

    Returns an empty result if Outlook isn't configured. `progress_cb(i,
    total, label)` is invoked during the body-fetch loop so the GUI can
    paint a progress bar.
    """
    try:
        import outlook_local as ol
    except Exception:
        return {"groups": [], "scanned": 0, "matched": 0, "unrouted": []}

    since = _utcnow() - _dt.timedelta(days=days)
    try:
        messages = ol.list_recent_messages(since=since, top=top)
    except Exception:
        return {"groups": [], "scanned": 0, "matched": 0, "unrouted": []}

    cache = _body_cache()
    cache_dirty = False

    by_claim: dict[str, dict[str, Any]] = {}
    unrouted: list[dict[str, Any]] = []
    matched = 0

    for i, m in enumerate(messages, start=1):
        if not is_xa_note_email(m):
            continue
        matched += 1
        msg_id = m.get("id") or ""
        subject = m.get("subject") or ""

        if progress_cb is not None:
            try:
                progress_cb(i, len(messages),
                            f"Reading XA note: {subject[:60]}")
            except Exception:
                pass

        # Fetch full body once and cache. bodyPreview is too short to
        # detect closer phrases reliably.
        prev_size = len(cache)
        body = _get_body(msg_id, cache=cache)
        if len(cache) != prev_size:
            cache_dirty = True
        if not body:
            body = m.get("bodyPreview") or ""

        # Identify the job. XA notification emails carry templated
        # Claim # / Insured: / Note: fields in the body — use those when
        # present because they're more reliable than the generic regex.
        is_notif = is_xa_notification(m)
        notif_fields = (parse_xa_notification(subject, body)
                        if is_notif else {})
        claim = (notif_fields.get("claim")
                 or extract_claim_number(subject)
                 or extract_claim_number(body))
        insured_hint = (notif_fields.get("insured")
                        or extract_insured_hint(subject))
        if not claim and not insured_hint:
            unrouted.append({
                "message_id": msg_id,
                "subject":    subject,
                "received":   m.get("receivedDateTime", ""),
            })
            continue
        # Group key prefers claim#, falls back to a normalized insured
        # name so jobs without a claim# in subject still aggregate.
        key = claim or f"name:{insured_hint.lower()}"

        bucket = by_claim.setdefault(key, {
            "claim":        claim,
            "insured_hint": insured_hint,
            "notes":        [],
            "card":         None,
            "card_lookup_attempted": False,
        })
        if not bucket["claim"] and claim:
            bucket["claim"] = claim
        if not bucket["insured_hint"] and insured_hint:
            bucket["insured_hint"] = insured_hint
        synth = email_to_synthetic_note(m, body)
        # For XA notification emails, replace the full Verisk-wrapper
        # body with just the actual note text so analyze_notes /
        # downstream snippet rendering shows the adjuster's message
        # rather than the auto-generated header + footer.
        if is_notif and notif_fields.get("note"):
            synth["body"] = notif_fields["note"]
            synth["_notification"] = True
        bucket["notes"].append(synth)

    if cache_dirty:
        try:
            _save_body_cache(cache)
        except Exception:
            pass

    # Per-group gap analysis.
    groups: list[dict[str, Any]] = []
    for key, bucket in by_claim.items():
        notes = bucket["notes"]
        analysis = xa_notes.analyze_notes(notes, stale_days=STALE_DAYS)
        if not analysis.get("is_stale") and not analysis.get(
                "open_commitments"):
            continue   # nothing to flag for this job
        bucket["analysis"] = analysis
        groups.append(bucket)

    # Cheap Trello-card lookup for the surviving groups only.
    if groups:
        try:
            import trello_client as tc
        except Exception:
            tc = None
        if tc is not None:
            for g in groups:
                if not g["claim"]:
                    continue
                try:
                    hits = tc.find_cards_by_name(g["claim"], max_results=3)
                except Exception:
                    hits = []
                # Verify by fetching and checking the desc actually
                # contains the claim# — Trello search matches name AND
                # desc, so a partial-substring match is possible.
                for h in hits:
                    try:
                        card = tc.get_card(h["card_id"], actions_limit=0)
                    except Exception:
                        card = None
                    if not card:
                        continue
                    desc = (card.get("desc") or "").lower()
                    if g["claim"].lower() in desc:
                        g["card"] = {
                            "id":       card.get("id", ""),
                            "name":     card.get("name", ""),
                            "shortUrl": card.get("shortUrl", ""),
                            "idBoard":  card.get("idBoard", ""),
                            "idList":   card.get("idList", ""),
                        }
                        # Mirror onto the group dict so the Hygiene
                        # panel's board filter can find these rows
                        # without special-casing their shape.
                        g["board_id"] = card.get("idBoard", "")
                        # XA assignment URL pulled from the desc the
                        # `LINKS / XACTANALYSIS LINK` row — surfaced as
                        # a direct-jump button on the XA-gap row in
                        # Hygiene so the user doesn't have to open the
                        # Trello card to chase the XA link.
                        try:
                            g["xa_link"] = tc.card_xa_link(card)
                        except Exception:
                            g["xa_link"] = ""
                        break

    # Sort: stalest first, then most open commitments, then claim asc.
    def _sort_key(g):
        a = g.get("analysis") or {}
        return (
            -(a.get("days_since_human") or 0),
            -len(a.get("open_commitments") or []),
            g.get("claim") or g.get("insured_hint") or "",
        )
    groups.sort(key=_sort_key)

    return {
        "groups":   groups,
        "scanned":  len(messages),
        "matched":  matched,
        "unrouted": unrouted,
    }


# ── Resolution / snooze ────────────────────────────────────────────────────
# Persistence shape: {claim_or_key: iso_resolved_at}. A scan with a newer
# note (timestamp > resolved_at) re-flags the gap automatically; older
# scans are filtered out by the GUI.

def is_resolved(group_key: str, *, latest_note_ts: _dt.datetime | None
                ) -> bool:
    """True when the user marked this gap resolved AFTER its latest note."""
    if not group_key:
        return False
    raw = per.get("xa_gap_resolved") or {}
    if not isinstance(raw, dict):
        return False
    iso = raw.get(group_key)
    if not iso:
        return False
    resolved_at = _parse_iso(iso)
    if resolved_at is None:
        return False
    if latest_note_ts is None:
        return True   # no notes — must be cleared until something new arrives
    return resolved_at > latest_note_ts


def mark_resolved(group_key: str) -> str:
    """Stamp `group_key` resolved at now-utc-iso. Returns the iso string."""
    if not group_key:
        return ""
    raw = per.get("xa_gap_resolved") or {}
    if not isinstance(raw, dict):
        raw = {}
    iso = _utcnow().isoformat(timespec="seconds")
    raw[group_key] = iso
    per.set_value("xa_gap_resolved", raw)
    return iso


def clear_resolved(group_key: str) -> None:
    if not group_key:
        return
    raw = per.get("xa_gap_resolved") or {}
    if not isinstance(raw, dict):
        return
    if group_key in raw:
        raw.pop(group_key, None)
        per.set_value("xa_gap_resolved", raw)


def filter_unresolved(groups: list[dict[str, Any]]
                       ) -> list[dict[str, Any]]:
    """Drop groups whose latest-note timestamp is older than the
    user-recorded resolved_at — those have been hand-cleared and don't
    need to keep flagging until new XA activity happens."""
    out: list[dict[str, Any]] = []
    for g in groups:
        key = g.get("claim") or f"name:{(g.get('insured_hint') or '').lower()}"
        analysis = g.get("analysis") or {}
        last = (analysis.get("last_human_note") or {}).get("timestamp")
        if is_resolved(key, latest_note_ts=last):
            continue
        out.append(g)
    return out


# ── CLI ────────────────────────────────────────────────────────────────────

def _cli(argv):
    if not argv or argv[0] not in ("preview", "scan"):
        print("Usage:")
        print("  python xa_email_ingest.py preview [--days=60] [--top=400]")
        return 1
    days = DEFAULT_DAYS_BACK
    top = DEFAULT_MAX_MESSAGES
    for a in argv[1:]:
        if a.startswith("--days="):
            try: days = int(a.split("=", 1)[1])
            except ValueError: pass
        elif a.startswith("--top="):
            try: top = int(a.split("=", 1)[1])
            except ValueError: pass

    def _progress(i, total, label):
        if i % 10 == 0:
            print(f"  [{i}/{total}] {label[:60]}")

    res = scan_inbox(days=days, top=top, progress_cb=_progress)
    print()
    print(f"Scanned {res['scanned']} messages, "
          f"{res['matched']} matched XA-note pattern, "
          f"{len(res['unrouted'])} unrouted.")
    groups = filter_unresolved(res["groups"])
    if not groups:
        print("(no XA gaps after filtering resolved)")
        return 0
    print(f"\n{len(groups)} job(s) flagged:")
    for g in groups:
        a = g.get("analysis") or {}
        claim = g.get("claim") or g.get("insured_hint") or "?"
        days_silent = a.get("days_since_human")
        commits = a.get("open_commitments") or []
        labels = sorted({c.get("label", "") for c in commits})
        card = g.get("card") or {}
        line = f"  - [{claim}]"
        if g.get("insured_hint") and claim != g["insured_hint"]:
            line += f"  {g['insured_hint']}"
        if card:
            line += f"  -> {card.get('name', '')[:40]}"
        line += f"  | {days_silent}d"
        if labels:
            line += f"  | open: {', '.join(labels)}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
