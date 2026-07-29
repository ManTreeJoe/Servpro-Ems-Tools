"""Adjuster-inquiry inbox monitor.

Watches the signed-in user's Outlook inbox for messages that look like
adjuster correspondence, matches the sender to a Trello card by
domain/name/claim#, and posts an inbound-receipt comment on the card so
nothing slips through the EMS@ inbox without a paper trail.

Match heuristics (in priority order, first hit wins):
    1. Claim number in subject/body matches the card's CLAIM NUMBER.
    2. Insurance carrier name in sender domain matches the card's
       INSURANCE COMPANY (e.g. `@statefarm.com` → State Farm card).
    3. Sender's name matches the card's ADJUSTER NAME.

Posts comment template:
    "Adjuster inquiry received from {name} <{email}>
     on {date}: {subject}
     [link]"

SLA tracking: per-card, the latest inbound + outbound timestamps are
stored in persistence. Cards with inbound > N days old and no outbound
since are surfaced as a separate scan result the Hygiene panel can
flag.

CLI:
    python adjuster_monitor.py preview [--days=2]
    python adjuster_monitor.py post     [--days=2] [--dry-run]
    python adjuster_monitor.py sla      [--threshold-days=2]

Backed by `outlook_local.py` (COM against the running Outlook desktop
session — no Azure app, no admin consent required).
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from typing import Any

import persistence as per
import trello_client as tc


# Carrier-domain hints. Sender domain match is fairly strong signal —
# adjusters almost always email from their carrier's mail servers.
# Mappings are case-insensitive substring against the email's domain.
_CARRIER_DOMAINS: tuple[tuple[str, str], ...] = (
    ("statefarm",   "State Farm"),
    ("aaa",         "AAA"),
    ("mercury",     "Mercury"),
    ("farmers",     "Farmers"),
    ("usaa",        "USAA"),
    ("allstate",    "Allstate"),
    ("libertymutual", "Liberty Mutual"),
    ("safeco",      "Safeco"),
    ("aegis",       "AEGIS"),
    ("travelers",   "Travelers"),
    ("nationwide",  "Nationwide"),
    ("bamboo",      "Bamboo"),
    ("amfam",       "AmFam"),
    ("connectins",  "Connect"),
    ("californiacasualty", "California Casualty"),
    ("chartis",     "AIG"),
    ("hartford",    "The Hartford"),
    ("chubb",       "Chubb"),
    ("metlife",     "MetLife"),
    ("statefarm",   "State Farm"),
    ("freedommortgage", "Freedom Mortgage"),
)

# Internal domains we never want to match — replies from our own staff
# and the @servpro10100 mailbox itself shouldn't get treated as inbound
# adjuster correspondence. Also includes XactAnalysis / Xactware system
# senders (donotreply@xactware.com etc.) — those are notification
# emails about notes being added to assignments, not inquiries from
# adjusters. They'd otherwise false-positive on claim-number matches
# scraped from the body.
_INTERNAL_DOMAIN_MARKERS = (
    "servpro10100.com", "servpronet.com",
    "xactware.com", "xactanalysis.com",
    # Various noreply / system patterns that occasionally appear
    "no-reply", "noreply", "donotreply", "do-not-reply",
)

# Promotional / transactional / vendor senders that shouldn't be treated
# as adjuster inquiries. Distinct from _INTERNAL so we can reason about
# the two filter gates separately (internal = "us", promotional = "spam
# from third parties"). Adding a sender here drops it before claim# or
# carrier-domain matching even runs — so a Docusign notification that
# happens to carry a claim# in its subject doesn't try to match cards.
_PROMOTIONAL_DOMAIN_MARKERS = (
    # Doc-signing platforms — they reference claim#s in subject lines
    "docusign.com", "docusign.net",
    # SaaS marketing senders that have leaked into the inbox
    "cotality.com", "mailchimp.com", "marketo.com",
    "constantcontact.com", "mailgun.", "sendgrid.", "hubspot.",
    "salesforce.com",
    # Consumer-brand promos that ended up in EMS@
    "valvoline.com",
    # Retailers + IAQ vendor promos seen in the EMS@ inbox
    "acehardware.com",         # acerewards@e1.acehardware.com newsletters
    "discoverbreeze.com",      # IAQ cassette vendor sales pitches
    "thecustomerfactor.com",   # bulk-mail handle
    # Workers-comp / business-insurance cold pitches
    "paramountexclusiveins.com",
    # Subcontractors / restoration vendors — they're not adjusters even
    # though they do reference claim/job numbers in their emails.
    "rocketshell.net",
)

# Local-part prefixes that almost always mean automated/bulk mail. Match
# on the whole email so `marketing@somecarrier.com` is filtered without
# blocking `john.marketing@statefarm.com` (real adjuster name with a
# misleading word).
_PROMOTIONAL_LOCAL_PREFIXES = (
    "marketing@", "news@", "info@", "notifications@",
    "newsletter@", "newsletters@", "webinar@", "webinars@",
    "webhook@", "team@", "hello@", "connect@", "customercare@",
    "support@",        # vendor support addresses — see Rocket Shell
    "restoration@",    # Cotality's marketing handle uses this prefix
    "mail@",           # generic bulk-mail handle (e.g. mail@thecustomerfactor.com)
    "rewards@",        # loyalty-program promos
    "promotions@", "promo@",
    "sales@",          # vendor sales pitches (e.g. sales@discoverbreeze.com)
    # Shared mailbox handles — vendors/subs route customer correspondence
    # through these. A real adjuster always writes from a personal-name
    # mailbox (jane.smith@statefarm.com), never from a shared inbox.
    # Caught the Safeguard Envirogroup case 2026-05-18.
    "clientservices@", "client.services@", "clientservice@",
    "operations@", "ops@", "admin@", "office@",
    "billing@", "ar@", "accounting@", "accounts@",
    "dispatch@", "scheduling@", "schedule@",
    "service@", "services@",
    "noreply@", "no.reply@",
)

# Substring patterns (NOT just prefixes) for local parts that are
# bulk-mail giveaways. Catches senders like `acerewards@*` where the
# loyalty-program identifier sits in the MIDDLE of the local part, so
# the `_PROMOTIONAL_LOCAL_PREFIXES` startswith check misses them.
_PROMOTIONAL_LOCAL_SUBSTRINGS = (
    "rewards@",
    "newsletter@",
)

# Personal email providers. A sender from one of these is almost
# never a real adjuster — adjusters write from carrier or independent-
# corporate domains. We don't OUTRIGHT block personal-domain senders
# (an adjuster on PTO occasionally replies from personal mail), but
# we DON'T let a claim# match alone tag them as adjuster inquiries.
# Promoted matches require an additional signal (sender's name found
# on the card's ADJUSTER NAME field) — see match_email_to_card.
_PERSONAL_EMAIL_DOMAINS = (
    "gmail.com", "googlemail.com",
    "yahoo.com", "ymail.com", "yahoo.co.uk", "yahoo.ca",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com",
    "msn.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com",
    "protonmail.com", "proton.me",
    "comcast.net", "verizon.net", "att.net", "sbcglobal.net",
    "cox.net", "charter.net", "earthlink.net",
)

# Display-name patterns that flag NON-adjuster senders even when they
# email about a job. Realtors, agents, attorneys, contractors, and
# the insured/customer themselves frequently reply to threads that
# carry a claim# in the body — without this filter they get tagged as
# adjuster inquiries. Match against the sender's display name OR the
# local-part of their address (e.g. "realtoryumiko@gmail.com").
_NON_ADJUSTER_ROLE_RE = re.compile(
    r"\b(?:realtor|real\s*estate|broker|"
    r"attorney|lawyer|paralegal|"
    r"contractor|contracting|plumber|plumbing|"
    r"roofer|roofing|electrician|electric(?:al)?|"
    r"property\s*manag(?:er|ement)|landlord|tenant|hoa|"
    r"homeowner|insured)\b",
    re.IGNORECASE,
)

_CLAIM_RE = re.compile(r"\b\d{6,}[-]?\d?\b")


# Phrases that explicitly request an estimate. When a matching email
# lands, it's promoted to a high-priority Estimate Request — the
# Hygiene panel renders a 🔴 ESTIMATE REQUEST chip and sorts these to
# the top of the section. Phrasings collected from real adjuster
# inbox samples; extend as new variants surface.
_EXPLICIT_REQUEST_PATTERNS = re.compile(
    # Each branch requires the literal word "estimate" near a request
    # verb / question phrasing. The `[\w-]+\s+` filler (≤4 tokens)
    # catches real-world variants like "please send me a separate
    # estimate" or "any update on the dry-out estimate" without
    # inviting unrelated mentions of the word. Hyphen included so
    # compound modifiers ("dry-out", "self-pay") count as one token.
    r"(?:please\s+(?:send|provide|forward|submit)\s+(?:[\w-]+\s+){0,4}estimate"
    r"|where(?:'s|\s+is)\s+(?:the\s+|my\s+|our\s+)?estimate"
    r"|(?:awaiting|waiting\s+for|need|requesting?)\s+(?:[\w-]+\s+){0,4}"
        r"(?:estimate|written\s+estimate|preliminary\s+estimate)"
    r"|(?:follow(?:ing)?[\s-]?up\s+on|status\s+(?:on|of))\s+"
        r"(?:[\w-]+\s+){0,4}estimate"
    r"|estimate\s+request"
    r"|when\s+can\s+(?:we|i)\s+expect\s+(?:[\w-]+\s+){0,4}estimate"
    r"|kindly\s+(?:send|provide|forward|submit)\s+(?:[\w-]+\s+){0,4}estimate"
    r"|any\s+(?:update|news)\s+on\s+(?:[\w-]+\s+){0,4}estimate"
    r"|send\s+(?:me|us)\s+(?:[\w-]+\s+){0,4}estimate)",
    re.IGNORECASE,
)


def is_explicit_estimate_request(text: str) -> bool:
    """True when the message text contains an explicit ask for the
    estimate. Substring search — checks subject + body combined."""
    if not text:
        return False
    return bool(_EXPLICIT_REQUEST_PATTERNS.search(text))


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _domain(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].strip().lower()


def _looks_internal(email: str) -> bool:
    """True for staff replies, internal noreply senders, and XA/Xactware
    system notifications. Substring match against the WHOLE email so
    noreply / donotreply patterns in the local part are caught even
    when the domain itself is a real carrier (e.g.
    `noreply@statefarm.com` — system, not the adjuster)."""
    em = (email or "").lower().strip()
    if not em:
        return True
    return any(marker in em for marker in _INTERNAL_DOMAIN_MARKERS)


def _looks_promotional(email: str) -> bool:
    """True for marketing/transactional/vendor senders that aren't
    adjuster correspondence. Match strategy:
      - Local-part prefix match (e.g. `marketing@*`) for automated sender
        conventions
      - Substring match for local-part identifiers that sit in the
        middle of compound senders (e.g. `acerewards@*` → `rewards@`)
      - Whole-email substring match for promotional domains
    Returns False for blank input — _looks_internal already handles that
    case as a guard."""
    em = (email or "").lower().strip()
    if not em:
        return False
    if any(em.startswith(p) for p in _PROMOTIONAL_LOCAL_PREFIXES):
        return True
    local = em.split("@", 1)[0] if "@" in em else em
    if any(sub.rstrip("@") in local for sub in _PROMOTIONAL_LOCAL_SUBSTRINGS):
        return True
    return any(marker in em for marker in _PROMOTIONAL_DOMAIN_MARKERS)


def _is_personal_domain(email: str) -> bool:
    """True when the sender's domain is a personal email provider
    (gmail, yahoo, icloud, comcast, …). Used to require an extra
    signal before tagging the message as an adjuster inquiry — a
    claim# in the body alone isn't enough for these senders, since
    realtors / insureds / contractors all routinely reply to threads
    that contain claim numbers."""
    d = _domain(email)
    return bool(d) and d in _PERSONAL_EMAIL_DOMAINS


def _looks_non_adjuster_role(*, display_name: str, local_part: str,
                              subject: str = "", body: str = "") -> bool:
    """True when the sender's display name OR email local-part signals
    a non-adjuster role (realtor, contractor, attorney, insured, …).
    Body is checked too for the rare case where the role only shows
    up in the signature block, but the body check is intentionally
    less aggressive — it has to be near 'from' / 'sincerely' to
    count, otherwise generic mentions of these roles inside a job
    description would over-trigger."""
    for s in (display_name, local_part):
        if s and _NON_ADJUSTER_ROLE_RE.search(s):
            return True
    return False


def _carrier_from_domain(email: str) -> str:
    """Return the canonical carrier display name when the sender's
    domain matches a known carrier, else ''."""
    d = _domain(email)
    if not d:
        return ""
    for marker, display in _CARRIER_DOMAINS:
        if marker in d:
            return display
    return ""


# ── Email → card matcher ─────────────────────────────────────────────────

def _claim_numbers_in_text(text: str) -> list[str]:
    if not text:
        return []
    # Strip whitespace runs and only keep digit sequences ≥ 6 chars
    return [m.group(0) for m in _CLAIM_RE.finditer(text)]


def match_email_to_card(message: dict) -> dict | None:
    """Best-effort match of an Outlook message to one Trello card.
    Returns the matched Trello card dict (from get_card) plus a
    `_match_reason` field, or None when no candidate looked good
    enough.

    This is intentionally conservative — a wrong match would post
    inbound-receipt comments to the wrong card. We require either
    claim# match OR (carrier match AND adjuster-name fuzzy match).
    """
    subject = (message.get("subject") or "")
    body = (message.get("bodyPreview") or "")
    text = f"{subject}\n{body}"
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    sender_addr = (sender.get("address") or "").lower()
    sender_name = (sender.get("name") or "").strip()
    if _looks_internal(sender_addr) or _looks_promotional(sender_addr):
        return None

    # Drop senders whose display name or local-part identifies them
    # as a non-adjuster role — realtors, contractors, attorneys, the
    # insured themselves. These people frequently reply to threads
    # that carry a claim# in the body; without this filter, they get
    # tagged as adjuster inquiries on the wrong cards.
    sender_local = sender_addr.split("@", 1)[0] if "@" in sender_addr else ""
    if _looks_non_adjuster_role(
            display_name=sender_name, local_part=sender_local,
            subject=subject, body=body):
        return None

    claim_candidates = _claim_numbers_in_text(text)
    carrier_hint = _carrier_from_domain(sender_addr)
    is_personal = _is_personal_domain(sender_addr)

    # Step 1: claim# search. Trello's /search endpoint indexes desc
    # AR / billing boards are excluded — hygiene + customer-complaint
    # scans should never link an email to an AR card (those cards by
    # design carry stale, billing-only follow-ups). Resolved once via
    # the cached id set in trello_client.
    excluded_ids = tc.quality_excluded_board_ids()

    def _ok(card_dict):
        return card_dict and card_dict.get("idBoard") not in excluded_ids

    # text, so claim numbers in the desc come back fast. We try the
    # first claim# we see and verify by fetching the card.
    #
    # Personal-domain senders (gmail/yahoo/icloud/etc.) need an
    # ADDITIONAL signal beyond the claim# — their last name must also
    # appear in the card's ADJUSTER NAME field. The realtor case
    # (CA & NV Realtor Yumiko <realtoryumiko@gmail.com>) was tagging
    # cards because the realtor's email body carried the insured's
    # claim#; with the personal-domain guard, claim# alone no longer
    # qualifies and the message lands in `unmatched` (where the user
    # can manually link if needed).
    sender_last = sender_name.split()[-1] if sender_name else ""
    for claim in claim_candidates[:3]:
        try:
            hits = tc.find_cards_by_name(claim, max_results=3)
        except Exception:
            hits = []
        for h in hits:
            if h.get("board") and h.get("board") in excluded_ids:
                continue
            try:
                card = tc.get_card(h["card_id"], actions_limit=20)
            except Exception:
                card = None
            if not _ok(card):
                continue
            fields = tc.parse_card_desc(card.get("desc"))
            ins = fields.get("INSURANCE INFORMATION") or {}
            cn = (ins.get("CLAIM NUMBER") or "").strip()
            if cn and claim in cn:
                if is_personal:
                    # Require the sender's last name to appear in the
                    # adjuster-name field, otherwise this is a non-
                    # adjuster on a personal mailbox.
                    adj = (ins.get("ADJUSTER NAME") or "").lower()
                    if not (sender_last
                             and sender_last.lower() in adj):
                        continue
                    card["_match_reason"] = (
                        f"claim# {claim} + adjuster {sender_name}")
                else:
                    card["_match_reason"] = f"claim# {claim}"
                return card

    # Step 2: carrier domain + sender-name fuzzy search. We need both
    # signals because carrier name alone (e.g. "Mercury" — common
    # English word) would over-match.
    if carrier_hint and sender_name:
        # Search by surname tokens of the sender — adjusters usually
        # appear on cards as "John Smith" or "Smith, John".
        last_name = sender_name.split()[-1] if sender_name else ""
        try:
            hits = tc.find_cards_by_name(last_name, max_results=8)
        except Exception:
            hits = []
        for h in hits:
            if h.get("board") and h.get("board") in excluded_ids:
                continue
            try:
                card = tc.get_card(h["card_id"], actions_limit=20)
            except Exception:
                card = None
            if not _ok(card):
                continue
            fields = tc.parse_card_desc(card.get("desc"))
            ins = fields.get("INSURANCE INFORMATION") or {}
            adjuster = (ins.get("ADJUSTER NAME") or "").lower()
            carrier = (ins.get("INSURANCE COMPANY") or "").lower()
            if (carrier_hint.lower() in carrier
                    and last_name.lower() in adjuster):
                card["_match_reason"] = (
                    f"carrier {carrier_hint} + adjuster {sender_name}")
                return card

    return None


# ── Inbound-receipt comment posting ──────────────────────────────────────

def _format_receipt(message: dict, *, body_override: str = "") -> str:
    """Build the Trello comment for an inbound adjuster email.

    The post is the raw email body, verbatim — no Subject/Received
    header, no Outlook link, no canonical receipt wrapper. The user
    wants the Trello card to read like a literal copy/paste of the
    email so they can scan it like a normal inbox message.

    `body_override`, when non-empty, is used in place of the message's
    stored body. Callers that fetch the full body at post time (vs the
    truncated preview captured at queue time) pass it in here. When
    the body is genuinely empty, fall back to the subject line so
    the comment isn't blank — but that's the only added text.
    """
    body = (body_override
            or (message.get("body") or "")
            or (message.get("bodyPreview") or "")
            or "").strip()
    if body:
        return body
    subject = (message.get("subject") or "").strip()
    return f"Subject: {subject}" if subject else ""


def _was_already_posted(card_id: str, message_id: str) -> bool:
    """Idempotency: persistence stores the set of (card_id, msg_id)
    pairs we've already commented for, so a re-run doesn't double-post."""
    posted = per.get("adjuster_receipt_posted") or {}
    if not isinstance(posted, dict):
        return False
    bucket = posted.get(card_id) or []
    return message_id in bucket


def _record_post(card_id: str, message_id: str, *, rec_iso: str = "") -> None:
    """Record a posted receipt to two persistence keys:
    - `adjuster_receipt_posted`: {card_id: [msg_id, ...]} for msg-id
      idempotency on re-runs.
    - `adjuster_receipt_posted_log`: {card_id: [YYYY-MM-DD, ...]} for
      the per-card-per-day cap to consult."""
    posted = per.get("adjuster_receipt_posted") or {}
    if not isinstance(posted, dict):
        posted = {}
    bucket = posted.get(card_id) or []
    if message_id not in bucket:
        bucket.append(message_id)
    posted[card_id] = bucket
    per.set_value("adjuster_receipt_posted", posted)

    # Daily-cap log. Use the message's received date so a backfill run
    # caps correctly even when scanning multiple days at once.
    day = (rec_iso or _utcnow().date().isoformat())[:10]
    log = per.get("adjuster_receipt_posted_log") or {}
    if not isinstance(log, dict):
        log = {}
    days = log.get(card_id) or []
    days.append(day)
    log[card_id] = days
    per.set_value("adjuster_receipt_posted_log", log)


def scan_and_post(*, days: int = 2, dry_run: bool = False,
                   progress_cb=None,
                   per_card_per_day_cap: int = 1,
                   auto_post: bool = False) -> dict[str, Any]:
    """Pull recent inbox messages, match each to a Trello card, and
    queue inbound-receipt entries for user approval.

    By default (auto_post=False) matched messages are NOT posted to
    Trello — they're written to the `adjuster_pending_approval`
    persistence key for the Hygiene panel to surface with ✓ Post /
    ✕ Dismiss buttons. The user-approval gate exists because the
    matcher has historically had false positives (realtors,
    contractors, environmental vendors with shared mailboxes) that
    leaked through the role/domain filters; gating on a human click
    means each new pattern only burns one keystroke instead of one
    bogus comment on a customer-visible card.

    `per_card_per_day_cap`: queue at most this many entries per card
    per calendar day (UTC). Email threads frequently bounce 5+ times
    in a day on the same claim — the user only needs to approve one
    receipt comment for that day. Within-day duplicates land in
    `skipped` with reason 'day_capped'.

    `auto_post=True` keeps the legacy behavior — skips the approval
    queue and posts directly. Reserved for one-off CLI use; the
    Hygiene panel and any scheduled scan should leave this False.

    Returns {"posted": [...], "unmatched": [...], "skipped": [...]}.
    When auto_post is False, "posted" actually means "queued for
    approval" — kept under the same key so existing callers
    (estimate_requests.detect_pending, etc.) keep working.
    `unmatched` contains message ids we couldn't confidently route —
    the GUI can show those so the user can manually link.
    """
    import outlook_local as ol  # COM-backed live backend (Graph blocked by IT)
    since = _utcnow() - _dt.timedelta(days=days)
    messages = ol.list_recent_messages(since=since, top=200)
    posted: list[dict] = []
    unmatched: list[dict] = []
    skipped: list[dict] = []
    total = len(messages)

    # Per-card per-day counter, keyed by (card_id, YYYY-MM-DD). Counts
    # both posts we make NOW and posts already recorded in persistence
    # for the same date — so a re-run within the same day doesn't
    # re-post once we've already capped.
    posts_today: dict[tuple, int] = {}
    posted_history = per.get("adjuster_receipt_posted_log") or {}
    if isinstance(posted_history, dict):
        for cid, entries in posted_history.items():
            if not isinstance(entries, list):
                continue
            for iso in entries:
                if not isinstance(iso, str) or len(iso) < 10:
                    continue
                key = (cid, iso[:10])
                posts_today[key] = posts_today.get(key, 0) + 1
    # Existing queue: pending entries already awaiting approval also
    # count against the day cap, so a re-run doesn't append a second
    # pending row for the same (card, day) pair.
    if not auto_post:
        for entry in (per.get("adjuster_pending_approval") or []):
            cid = (entry or {}).get("card_id") or ""
            iso = (entry or {}).get("received") or ""
            if not cid or len(iso) < 10:
                continue
            key = (cid, iso[:10])
            posts_today[key] = posts_today.get(key, 0) + 1
    pending_message_ids = {
        (entry or {}).get("message_id")
        for entry in (per.get("adjuster_pending_approval") or [])
        if (entry or {}).get("message_id")}
    dismissed_message_ids = set(
        per.get("adjuster_pending_dismissed") or [])

    for i, m in enumerate(messages, start=1):
        if progress_cb is not None:
            try: progress_cb(i, total, m.get("subject", "")[:60])
            except Exception: pass
        msg_id = m.get("id") or ""
        sender_addr = (((m.get("from") or {}).get("emailAddress") or {})
                        .get("address", ""))
        if _looks_internal(sender_addr) or _looks_promotional(sender_addr):
            continue   # internal / system / promotional mail
        # Detect explicit estimate requests before matching, so even
        # unmatched (no Trello card) rows carry the priority flag.
        explicit = is_explicit_estimate_request(
            (m.get("subject", "") or "") + "\n"
            + (m.get("bodyPreview", "") or ""))
        card = match_email_to_card(m)
        if card is None:
            unmatched.append({
                "message_id":       msg_id,
                "subject":          m.get("subject", ""),
                "from":             sender_addr,
                "received":         m.get("receivedDateTime", ""),
                "explicit_request": explicit,
            })
            continue
        cid = card.get("id", "")
        if _was_already_posted(cid, msg_id):
            skipped.append({"message_id": msg_id, "card_id": cid,
                             "reason": "already_posted"})
            continue
        if (not auto_post) and msg_id in pending_message_ids:
            skipped.append({"message_id": msg_id, "card_id": cid,
                             "reason": "already_pending_approval"})
            continue
        if (not auto_post) and msg_id in dismissed_message_ids:
            skipped.append({"message_id": msg_id, "card_id": cid,
                             "reason": "user_dismissed"})
            continue
        # Per-card-per-day cap. Use the message's received date so a
        # re-run picking up yesterday's mail still gets one post for
        # yesterday.
        rec_iso = (m.get("receivedDateTime") or "")[:10] or _utcnow().date(
            ).isoformat()
        cap_key = (cid, rec_iso)
        if posts_today.get(cap_key, 0) >= per_card_per_day_cap:
            skipped.append({"message_id": msg_id, "card_id": cid,
                             "reason": "day_capped",
                             "subject": m.get("subject", "")})
            continue
        sender_email = (((m.get("from") or {}).get("emailAddress") or {})
                         .get("address", ""))
        sender_name = (((m.get("from") or {}).get("emailAddress") or {})
                        .get("name", ""))
        entry = {
            "message_id":       msg_id,
            "card_id":          cid,
            "card_name":        card.get("name", ""),
            "card_url":         card.get("shortUrl", ""),
            "board_id":         card.get("idBoard", ""),
            "match":            card.get("_match_reason", ""),
            "subject":          m.get("subject", ""),
            "received":         m.get("receivedDateTime", ""),
            "sender_email":     sender_email,
            "sender_name":      sender_name,
            "email_link":       m.get("webLink", ""),
            "explicit_request": explicit,
            "preview":          (m.get("bodyPreview") or "")[:240],
            "comment_text":     _format_receipt(m),
            "queued_at":        _utcnow().isoformat(timespec="seconds"),
        }
        if dry_run:
            posts_today[cap_key] = posts_today.get(cap_key, 0) + 1
            posted.append(entry)
            continue
        if auto_post:
            try:
                tc.post_comment(cid, _format_receipt(m))
                _record_post(cid, msg_id, rec_iso=rec_iso)
            except Exception as ex:
                skipped.append({
                    "message_id": msg_id, "card_id": cid,
                    "error": str(ex)})
                continue
        else:
            try:
                _queue_pending(entry)
                pending_message_ids.add(msg_id)
            except Exception as ex:
                skipped.append({
                    "message_id": msg_id, "card_id": cid,
                    "error": str(ex)})
                continue
        posts_today[cap_key] = posts_today.get(cap_key, 0) + 1
        posted.append(entry)
    return {"posted": posted, "unmatched": unmatched, "skipped": skipped}


# ── Pending-approval queue ───────────────────────────────────────────────

def _queue_pending(entry: dict) -> None:
    """Append a match record to the user-approval queue. Replaces any
    prior entry with the same message_id so re-runs idempotently
    update (e.g. card_name changed on Trello) instead of stacking."""
    queue = per.get("adjuster_pending_approval") or []
    if not isinstance(queue, list):
        queue = []
    mid = entry.get("message_id") or ""
    queue = [e for e in queue if (e or {}).get("message_id") != mid]
    queue.append(entry)
    per.set_value("adjuster_pending_approval", queue)


def list_pending() -> list[dict]:
    """All match records currently waiting for ✓ Post / ✕ Dismiss."""
    queue = per.get("adjuster_pending_approval") or []
    if not isinstance(queue, list):
        return []
    return [e for e in queue if isinstance(e, dict)]


def _drop_pending(message_id: str) -> dict | None:
    """Pop the entry by message_id; return it (or None when missing)."""
    queue = per.get("adjuster_pending_approval") or []
    if not isinstance(queue, list):
        return None
    keep, dropped = [], None
    for e in queue:
        if isinstance(e, dict) and e.get("message_id") == message_id:
            dropped = e
            continue
        keep.append(e)
    per.set_value("adjuster_pending_approval", keep)
    return dropped


def approve_pending(message_id: str) -> bool:
    """User clicked ✓ Post on a pending entry. Post the email's raw
    body (with a `Received: … · Subject: …` header if missing from
    the body itself), record the post for idempotency, then drop
    the queue entry. Returns True on success.

    Fetches the FULL body via `outlook_local.get_message_body` at
    post time so the Trello comment isn't capped at the 240-char
    preview stored on the queue entry. Falls back to the preview
    when Outlook isn't reachable.
    """
    entry = _drop_pending(message_id)
    if entry is None:
        return False
    cid = entry.get("card_id") or ""
    if not cid:
        return False
    # Fetch the full email body lazily — preview on the queue entry
    # is only 240 chars and templated adjuster notes blow past that
    # in the first paragraph. Log on failure so a silent fall-back
    # to the truncated preview isn't invisible to the user.
    body_full = ""
    try:
        import outlook_local as _ol
        body_full = _ol.get_message_body(message_id) or ""
        if not body_full:
            try:
                import ems_log
                ems_log.warn("adjuster_monitor",
                             f"approve_pending: empty body from outlook_local "
                             f"for {message_id!r}; falling back to preview")
            except Exception:
                pass
    except Exception as _ex:
        body_full = ""
        try:
            import ems_log
            ems_log.warn("adjuster_monitor",
                         f"approve_pending: outlook_local body-fetch failed "
                         f"({_ex!r}); falling back to preview")
        except Exception:
            pass
    comment = _format_receipt({
        "subject": entry.get("subject"),
        "receivedDateTime": entry.get("received"),
        "bodyPreview": entry.get("preview") or "",
        "from": {"emailAddress": {
            "name": entry.get("sender_name"),
            "address": entry.get("sender_email"),
        }},
    }, body_override=body_full)
    try:
        tc.post_comment(cid, comment)
        rec_iso = (entry.get("received") or "")[:10] or _utcnow().date(
            ).isoformat()
        _record_post(cid, message_id, rec_iso=rec_iso)
        return True
    except Exception:
        _queue_pending(entry)
        return False


def dismiss_pending(message_id: str) -> bool:
    """User clicked ✕ Dismiss on a pending entry. Drop it from the
    queue AND record the message_id in a separate dismissed list so a
    re-scan doesn't immediately re-queue the same false positive."""
    entry = _drop_pending(message_id)
    dismissed = per.get("adjuster_pending_dismissed") or []
    if not isinstance(dismissed, list):
        dismissed = []
    if message_id and message_id not in dismissed:
        dismissed.append(message_id)
        # Bound the dismissed history so it doesn't grow unboundedly.
        # 2000 entries ≈ a year of inbox at typical volume — more than
        # enough to keep re-runs idempotent.
        if len(dismissed) > 2000:
            dismissed = dismissed[-2000:]
        per.set_value("adjuster_pending_dismissed", dismissed)
    return entry is not None


def find_sla_violations(*, threshold_days: int = 2) -> list[dict]:
    """Cards with the most recent posted-receipt timestamp older than
    `threshold_days` and no follow-up comment from our team since.
    Reads the `adjuster_receipt_posted_log` (card_id → [YYYY-MM-DD]) for the
    receipt date, then a single get_card per card to check for a reply.

    NOTE: this used to scan comments for a "📨 Adjuster inquiry received"
    prefix, but `_format_receipt` posts the raw email body verbatim (no
    wrapper — user's format rule), so that prefix was never present and the
    whole feature silently returned []. We now take the receipt date from
    the log we write in `_record_post` and treat ANY team comment after that
    day as the follow-up reply.
    """
    log = per.get("adjuster_receipt_posted_log") or {}
    if not isinstance(log, dict):
        return []
    cutoff = _utcnow() - _dt.timedelta(days=threshold_days)

    def _parse_day(d):
        try:
            return _dt.datetime.fromisoformat((d or "")[:10])
        except (ValueError, TypeError):
            return None

    out: list[dict] = []
    for cid, days in log.items():
        if not days:
            continue
        # Most recent receipt we posted for this card.
        receipt_dt = None
        for d in days:
            pd = _parse_day(d)
            if pd is not None and (receipt_dt is None or pd > receipt_dt):
                receipt_dt = pd
        if receipt_dt is None or receipt_dt > cutoff:
            continue   # unparseable or too recent to flag
        try:
            card = tc.get_card(cid, actions_limit=20)
        except Exception:
            card = None
        if not card:
            continue
        # Any team comment on a day AFTER the receipt = we replied → SLA met.
        replied = False
        for a in card.get("actions") or []:
            if a.get("type") != "commentCard":
                continue
            a_dt = _parse_iso(a.get("date") or "")
            if a_dt is not None and a_dt.date() > receipt_dt.date():
                replied = True
                break
        if replied:
            continue
        out.append({
            "card_id":      cid,
            "card_name":    card.get("name", ""),
            "card_url":     card.get("shortUrl", ""),
            "receipt_iso":  receipt_dt.isoformat(timespec="seconds"),
            "days_silent":  (_utcnow() - receipt_dt).days,
        })
    return out


# ── CLI ─────────────────────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python adjuster_monitor.py preview [--days=N]")
        print("  python adjuster_monitor.py post    [--days=N] [--dry-run] [--auto-post]")
        print("  python adjuster_monitor.py pending")
        print("  python adjuster_monitor.py sla     [--threshold-days=N]")
        print("")
        print("`post` queues matches for Hygiene-panel approval by default.")
        print("Pass --auto-post to skip the approval gate (legacy behavior).")
        return 1
    cmd = argv[0]
    days = 2
    dry = False
    threshold = 2
    auto = False
    for a in argv[1:]:
        if a.startswith("--days="):
            try: days = int(a.split("=", 1)[1])
            except ValueError: pass
        elif a.startswith("--threshold-days="):
            try: threshold = int(a.split("=", 1)[1])
            except ValueError: pass
        elif a == "--dry-run":
            dry = True
        elif a == "--auto-post":
            # Legacy "post-without-approval" behavior. Kept for one-off
            # cleanup runs; routine scans should leave this off so the
            # Hygiene panel surfaces every match for ✓ Post approval.
            auto = True
    if cmd == "preview":
        result = scan_and_post(days=days, dry_run=True)
        print(f"Matched: {len(result['posted'])} | "
              f"Unmatched: {len(result['unmatched'])} | "
              f"Skipped (already posted): {len(result['skipped'])}")
        for p in result["posted"][:30]:
            print(f"  ✓ {p['card_name'][:50]:50s}  ← {p['match']}")
        for u in result["unmatched"][:10]:
            print(f"  ? {u['subject'][:60]:60s}  from {u['from']}")
        return 0
    if cmd == "post":
        result = scan_and_post(days=days, dry_run=dry, auto_post=auto)
        marker = "[DRY-RUN] " if dry else ("" if auto else "[QUEUED] ")
        verb = "Posted" if auto else ("Would queue"
                                       if dry else "Queued for approval")
        print(f"{marker}{verb}: {len(result['posted'])} | "
              f"Unmatched: {len(result['unmatched'])} | "
              f"Skipped: {len(result['skipped'])}")
        return 0
    if cmd == "pending":
        pending = list_pending()
        if not pending:
            print("✓ No adjuster inquiries awaiting approval.")
            return 0
        for e in pending:
            print(f"  • {e.get('card_name', '')[:55]:55s}  ← {e.get('match', '')}")
            print(f"      from {e.get('sender_email', '')}  "
                  f"({e.get('received', '')[:16].replace('T', ' ')})")
        return 0
    if cmd == "sla":
        flagged = find_sla_violations(threshold_days=threshold)
        if not flagged:
            print(f"✓ No SLA violations (>{threshold}d without reply).")
            return 0
        for f in flagged:
            print(f"  [{f['days_silent']}d]  {f['card_name'][:60]}")
            print(f"     {f['card_url']}")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
