"""Docusign-pending tracker — parallel to docusketch_requests.

Tracks paperwork sent for e-signature on a job. Two states:

  • state="pending_signature" — paperwork was emailed to a known address
    (from the Trello card desc), waiting for the signed return. Daily
    nag in Hygiene until the user clicks ✓ Received.
  • state="pending_email" — the Trello card has no email field, so the
    user asked the office (Kimberly, by default) to call the insured
    and get one. Hygiene shows the "✉ Got email" button which, once
    clicked with the new address, transitions the entry to
    pending_signature and posts the paperwork comment.

Persistence:
    state.json["docusign_requests"] = {card_id: entry}
    entry = {
        card_id, client, card_name, card_url, board_id, list_id, lane,
        requested, comment_posted, email, state, paperwork_sent_at
    }

Public API:
    request(card_id, *, client_name="", post_comment=True) -> entry|None
    update_email(card_id, email, *, post_comment=True) -> entry|None
    resolve(card_id) -> None
    pending_requests() -> [entry, ...]
    is_pending(card_id) -> bool
    KIMBERLY_HANDLE — Trello @mention used when no email is on the card
    DEFAULT_SENT_NOTE / DEFAULT_NEEDS_EMAIL_NOTE — comment templates
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from typing import Any

import persistence as per
import trello_client as tc


# ── Customer-facing DocuSign request email ───────────────────────────
# The body the office sends to the insured asking them to e-sign the
# closeout paperwork. The property city is auto-filled from the job's
# address; the office phone comes from config so it follows the active
# department (IE vs OC) — falls back to the IE number when unset.
OFFICE_PHONE = "951-398-3240"


def _office_phone() -> str:
    try:
        import config
        return config.office_phone()
    except Exception:
        return OFFICE_PHONE

# Street-type tokens — the city in a comma-less address ("5671 Northwood
# Dr. Riverside 92509") is whatever follows the LAST of these.
_STREET_SUFFIX_RE = _re.compile(
    r"\b(?:st|street|ave|avenue|blvd|boulevard|dr|drive|rd|road|ct|court|"
    r"ln|lane|way|pl|place|cir|circle|ter|terrace|pkwy|parkway|hwy|highway|"
    r"trl|trail|loop|run|pass|row|sq|square|aly|alley|walk|path|pt|point|"
    r"cyn|canyon|cv|cove|xing|crossing|hl|hill|mnr|manor|byp|bypass)\b\.?",
    _re.IGNORECASE)


def city_from_address(address: str) -> str:
    """Best-effort city out of a US property address. Handles
    'Street, City, ST ZIP', comma-less 'Street City ZIP', and multi-word
    cities ('San Jacinto', 'Moreno Valley'). Returns '' when nothing
    usable is found — caller should fall back to a blank/placeholder."""
    if not address:
        return ""
    s = " ".join(str(address).split())
    # Strip a trailing ZIP / ZIP+4, then an optional trailing state token.
    s = _re.sub(r"\s*\b\d{5}(?:-\d{4})?\b\s*$", "", s)
    s = _re.sub(r"[,\s]+(?:[A-Za-z]{2}|california|calif\.?)\s*$", "", s,
                flags=_re.IGNORECASE).rstrip(", ")
    if not s:
        return ""
    if "," in s:                       # "…Street, City"
        return s.split(",")[-1].strip()
    matches = list(_STREET_SUFFIX_RE.finditer(s))
    if matches:
        tail = s[matches[-1].end():].strip()
        # Drop a leading unit token ("Apt 4" / "Unit 2" / "#3").
        tail = _re.sub(r"^\s*(?:apt\.?|unit|ste\.?|suite|#)\s*\w+\s*", "",
                       tail, flags=_re.IGNORECASE).strip()
        if tail:
            return tail
    return s.split()[-1] if s.split() else ""


def customer_email_text(city: str = "") -> str:
    """The closeout DocuSign request body sent to the insured. `city`
    auto-fills the '…at your property in <city>' clause; omitted cleanly
    when blank."""
    loc = f" in {city.strip()}" if (city or "").strip() else ""
    return (
        "Hello, as Servpro has completed mitigation services at your "
        f"property{loc}, we will need the following form(s) to be signed "
        "in order to close out this part of your claim with us. Please "
        "sign at your earliest convenience and if you have any questions, "
        f"please contact our office at {_office_phone()}. Thank you."
    )


# Trello @-mention handle used when paperwork is blocked on getting
# an email from the insured. Set to a literal "@kimberly" so Trello
# pings the right account if her username matches; user can edit the
# composer dialog before posting to tag a different person.
KIMBERLY_HANDLE = "@kimberlyz_"

DEFAULT_SENT_NOTE = "📝 Docusign paperwork sent to {email} — awaiting signature."
DEFAULT_NEEDS_EMAIL_NOTE = (
    "📝 {handle} — please call the insured to get an email address "
    "for Docusign paperwork. We'll send it once you reply with the email.")


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
    raw = per.get("docusign_requests") or {}
    return raw if isinstance(raw, dict) else {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    per.set_value("docusign_requests", data)


# Keys to try in the card desc when extracting the insured's email.
# CUSTOMER INFORMATION carries the insured email on most templated
# cards; INSURED appears on a small minority. ADJUSTER EMAIL is
# excluded — adjusters aren't the docusign recipient.
_EMAIL_DESC_KEYS = [
    ("CUSTOMER INFORMATION", "EMAIL"),
    ("CUSTOMER INFORMATION", "CUSTOMER EMAIL"),
    ("CUSTOMER INFORMATION", "INSURED EMAIL"),
    ("INSURED INFORMATION",  "EMAIL"),
    ("INSURED INFORMATION",  "INSURED EMAIL"),
    ("PROPERTY DETAILS",     "EMAIL"),
    ("CONTACT INFORMATION",  "EMAIL"),
]


def extract_insured_email(card):
    """Pull the insured's email from a card's parsed desc. Returns ""
    when no plausible key carries an address."""
    if not card:
        return ""
    try:
        fields = tc.parse_card_desc(card.get("desc"))
    except Exception:
        return ""
    for section, key in _EMAIL_DESC_KEYS:
        sec = fields.get(section) or {}
        val = (sec.get(key) or "").strip()
        if "@" in val and "." in val.split("@", 1)[-1]:
            return val
    return ""


def request(card_id, *, client_name="", post_comment=True):
    """Record a pending Docusign request for a Trello card.

    Workflow split by what the card carries:
      • Email present → posts DEFAULT_SENT_NOTE with the email
        substituted, records state="pending_signature".
      • No email     → posts DEFAULT_NEEDS_EMAIL_NOTE with KIMBERLY_HANDLE
        substituted, records state="pending_email".

    Returns the recorded entry, or None if the card couldn't be fetched."""
    if not card_id:
        return None
    try:
        card = tc.get_card(card_id, actions_limit=0)
    except Exception:
        card = None
    if not card:
        return None

    email = extract_insured_email(card)
    if email:
        state = "pending_signature"
        note = DEFAULT_SENT_NOTE.format(email=email)
    else:
        state = "pending_email"
        note = DEFAULT_NEEDS_EMAIL_NOTE.format(handle=KIMBERLY_HANDLE)

    posted_ok = True
    if post_comment:
        try:
            tc.post_comment(card_id, note)
        except Exception:
            posted_ok = False

    lane_name = ""
    try:
        lane_name = tc.get_lane_name(card.get("idBoard"),
                                       card.get("idList"))
    except Exception:
        pass

    now_iso = _utcnow().isoformat(timespec="seconds")
    entry = {
        "card_id":   card_id,
        "client":    client_name or card.get("name", ""),
        "card_name": card.get("name", ""),
        "card_url":  card.get("shortUrl", ""),
        "board_id":  card.get("idBoard", ""),
        "list_id":   card.get("idList", ""),
        "lane":      lane_name,
        "requested": now_iso,
        "comment_posted": posted_ok,
        "email":     email,
        "state":     state,
        "paperwork_sent_at": now_iso if state == "pending_signature" else "",
    }
    data = _load()
    data[card_id] = entry
    _save(data)
    return entry


def update_email(card_id, email, *, post_comment=True):
    """Transition a pending_email entry to pending_signature once the
    user has the insured's address. Posts the "Docusign sent to…"
    comment so the Trello timeline reflects the handoff."""
    if not card_id or not (email or "").strip():
        return None
    data = _load()
    entry = data.get(card_id)
    if not entry:
        return None
    email = email.strip()
    entry["email"] = email
    entry["state"] = "pending_signature"
    entry["paperwork_sent_at"] = _utcnow().isoformat(timespec="seconds")
    if post_comment:
        try:
            tc.post_comment(card_id,
                             DEFAULT_SENT_NOTE.format(email=email))
            entry["comment_posted"] = True
        except Exception:
            entry["comment_posted"] = False
    data[card_id] = entry
    _save(data)
    return entry


def add_manual(client, *, email=""):
    """Create a Docusign pending entry WITHOUT a Trello card backing it.

    Used from the Hygiene panel's '+ Add Docusign manually' button when
    the user wants to track paperwork they sent outside the normal
    right-click flow (no card pinned yet, ad-hoc reminders, etc.).

    State follows the same email/no-email logic as `request()`:
      • email given → state="pending_signature"
      • email blank → state="pending_email" (so the Hygiene row offers
        the ✉ Got email button)

    Synthetic key shape: 'manual:<client-slug>:<unix-ts>'. The leading
    'manual:' prefix means real Trello card-id lookups (which are always
    24-hex) won't collide with these. Returns the recorded entry."""
    client = (client or "").strip()
    if not client:
        return None
    email = (email or "").strip()
    state = "pending_signature" if email else "pending_email"
    now_iso = _utcnow().isoformat(timespec="seconds")
    slug = "".join(c.lower() if c.isalnum() else "-" for c in client).strip("-")
    fake_id = f"manual:{slug or 'unknown'}:{int(_utcnow().timestamp())}"
    entry = {
        "card_id":   fake_id,
        "client":    client,
        "card_name": client,
        "card_url":  "",
        "board_id":  "",
        "list_id":   "",
        "lane":      "",
        "requested": now_iso,
        "comment_posted": False,
        "email":     email,
        "state":     state,
        "paperwork_sent_at": now_iso if state == "pending_signature" else "",
        "manual":    True,
    }
    data = _load()
    data[fake_id] = entry
    _save(data)
    return entry


def resolve(card_id):
    """Mark a Docusign request resolved (signed paperwork received,
    or the user manually decided it's no longer needed). Removes the
    entry."""
    if not card_id:
        return
    data = _load()
    if card_id in data:
        data.pop(card_id, None)
        _save(data)


def is_pending(card_id):
    return bool(card_id) and card_id in _load()


def pending_requests():
    """All unresolved Docusign requests, sorted oldest-first so the
    most-overdue items surface at the top of the Hygiene section."""
    data = _load()
    out = []
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
