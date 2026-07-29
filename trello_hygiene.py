"""Trello card hygiene + handoff scans.

Pure logic, no UI. Two top-level scans:

    scan_card(card, *, lane_name) -> [Violation, ...]
        Per-card rules (owner, follow-up date, comment freshness, next-action).

    scan_lane_moves(*, hours_back=24) -> [Violation, ...]
        Cards that moved lanes recently without a handoff note in the
        comment immediately after the move.

Both rules-engines emit the same Violation shape so callers (the GUI panel,
end-of-day digest, etc.) can render a single homogeneous list.

Maps to:
- "Accountability Standard" in EMS Admin Job Duties: every card must show
  assigned owner / clear next action / follow-up date / updated note.
- Lane move = ownership transfer + clear handoff note.

Heavy lifting (board enumeration, card fetch, comment paging) is delegated
to trello_client. This module only owns the rule logic and the
violation-formatting.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import trello_client as tc


# ── Tunables ────────────────────────────────────────────────────────────────
# How long a card can sit in a lane without a comment before we flag it.
# Per-lane overrides via config["trello_hygiene_stale_days_per_lane"] —
# e.g. waiting-on-customer lanes might tolerate 14 days; active lanes 3.
DEFAULT_STALE_DAYS = 7

# Lanes that are explicitly "no movement expected" — silence here is fine
# regardless of duration. Match against lowercased lane name (substring).
_PARKED_LANE_MARKERS = (
    "completed", "closed", "archive", "done", "finished",
    "future", "follow up - long", "long term hold",
)

# Activity-prefilter threshold: cards in a parked lane that haven't seen
# any update in this many days are dropped before the per-card get_card
# fetch. Saves a full Trello round-trip per skipped card and removes
# unactionable "missing owner on a 2-year-old closed job" noise.
_PREFILTER_PARKED_AGE_DAYS = 90

# Board-name substrings that the quality scan skips entirely. AR is a
# billing-follow-up board, not an active-work board — its cards are by
# design quiet for weeks and would dominate the Trello quality tab with
# noise that isn't actionable from there. (The dedicated XA apology
# section in ar_followup still reads the AR board directly.) The
# canonical list lives in trello_client.QUALITY_EXCLUDED_BOARD_NAMES;
# this alias is kept for legacy callers but the centralised check
# below is what every new path should use.
_QUALITY_BOARD_NAME_EXCLUDES = tc.QUALITY_EXCLUDED_BOARD_NAMES

# Customer-complaint keyword patterns. Each entry is (regex_pattern,
# severity, short_label). Severity drives the row accent color; the
# label is what shows in the panel before the matched snippet.
# Patterns deliberately tight — "manager" / "review" alone are too
# noisy in restoration-job comments ("manager will sign", "I'll review
# the scope"). Compound phrases avoid those false positives.
_COMPLAINT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\bcomplaints?\b",                       "warn",  "complaint"),
    (r"\bcomplain(?:ing|ed)?\b",               "warn",  "complaint"),
    (r"\b(?:lawyer|attorney|legal counsel)\b", "error", "legal"),
    (r"\b(?:lawsuit|suing|will sue)\b",        "error", "lawsuit"),
    (r"\bBBB\b",                               "error", "BBB"),
    (r"\b(?:yelp|google review|1[\s-]star|bad review|negative review)\b",
                                               "warn",  "review"),
    (r"\brefund\b",                            "warn",  "refund"),
    (r"\bdisappoint(?:ed|ing|ment)\b",         "warn",  "complaint"),
    (r"\b(?:unhappy|frustrated|upset)\s+(?:customer|insured|client|with)",
                                               "warn",  "customer-upset"),
    (r"\bnot happy\b",                         "warn",  "complaint"),
    (r"\b(?:speak|talk)\s+to\s+(?:your|a|the)\s+(?:manager|supervisor)",
                                               "error", "escalation"),
    (r"\bescalat(?:e|ed|ing|ion)\b",           "warn",  "escalation"),
)
_COMPLAINT_LOOKBACK_DAYS = 30
_COMPLAINT_SNIPPET_CHARS = 140

# A handoff comment ought to mention what's next. Heuristics: an @mention
# pulls the new owner's attention, the words "handoff", "next:", or "next
# step" indicate intent, or a fairly long comment (≥ 60 chars) signals
# someone actually wrote prose. Cards that move lanes with only a one-word
# comment ("ok", "done") DON'T qualify — that's the failure mode this rule
# is designed to catch.
_HANDOFF_MIN_CHARS = 60
_HANDOFF_KEYWORDS_RE = re.compile(
    r"(?:^|\s)(?:next\s*:|next step|handoff|hand-off|hand off|"
    r"@\w[\w.-]*)",
    re.IGNORECASE,
)

# Description fields where the owner might be specified manually (e.g.
# "Owner: Sam"). Card members are the primary signal — these are fallback.
_DESC_OWNER_KEYS = ("OWNER", "ASSIGNED TO", "ASSIGNED OWNER")
_NEXT_ACTION_KEYS = ("NEXT ACTION", "NEXT STEP", "NEXT")


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_iso(iso: str) -> _dt.datetime | None:
    """Trello ISO-8601 (`2026-05-05T18:18:18.113Z`) → naive UTC datetime.
    Returns None on any failure so callers can treat missing timestamps as
    'unknown' without crashing the whole scan."""
    if not iso:
        return None
    try:
        s = iso.split(".")[0].rstrip("Z")
        return _dt.datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


def _utcnow() -> _dt.datetime:
    # Naive UTC. We deliberately avoid tz-aware datetimes so subtraction
    # against the also-naive parsed Trello timestamps stays well-defined
    # — datetime.UTC + naive tz-naive mixing raises TypeError.
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _days_between(a: _dt.datetime | None, b: _dt.datetime | None) -> float | None:
    """Whole + fractional days between two datetimes, or None if either is
    missing. Sign reflects (a - b) so callers can ask 'how long since X' by
    passing (now, X)."""
    if a is None or b is None:
        return None
    delta = a - b
    return delta.total_seconds() / 86400


def _flatten_desc(desc: str) -> dict[str, str]:
    """Pull templated `**SECTION**` + `Key: Value` pairs out of a card desc
    into a flat {KEY_UPPERCASE: value} map. Section headers are dropped —
    we only care about the field-level data for hygiene rules."""
    if not desc:
        return {}
    flat: dict[str, str] = {}
    for section in tc.parse_card_desc(desc).values():
        for key, val in section.items():
            if val and val.strip():
                flat.setdefault(key, val.strip())
    return flat


def _last_comment(card: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most-recent commentCard action from the card's bundled
    actions list (newest-first per Trello). None when the card has no
    comments. Only the inline 50-action window is consulted — older
    comments would already be older than any reasonable staleness
    threshold."""
    for a in card.get("actions") or []:
        if a.get("type") == "commentCard":
            return a
    return None


def _last_lane_move(card: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most-recent updateCard action that changed idList,
    or None when the card hasn't moved in the action window."""
    for a in card.get("actions") or []:
        if a.get("type") == "updateCard" and "listAfter" in (a.get("data") or {}):
            return a
    return None


def _is_parked_lane(lane_name: str) -> bool:
    """Lanes where silence is the desired state (Closed, Archived, Future).
    Hygiene staleness is suppressed for these — they'd flag every card
    forever if we didn't carve them out."""
    nm = (lane_name or "").lower()
    return any(marker in nm for marker in _PARKED_LANE_MARKERS)


def _stale_days_for_lane(lane_name: str, overrides: dict[str, int] | None) -> int:
    """Resolve the per-lane stale threshold via the config override map,
    falling back to DEFAULT_STALE_DAYS. Lookup is case-insensitive
    substring — `{"pending review": 14}` matches a lane called
    'PENDING REVIEW .'."""
    if not overrides:
        return DEFAULT_STALE_DAYS
    nm = (lane_name or "").lower()
    for key, days in overrides.items():
        if not key:
            continue
        if str(key).lower() in nm:
            try:
                return max(1, int(days))
            except (TypeError, ValueError):
                continue
    return DEFAULT_STALE_DAYS


# ── Violation construction ─────────────────────────────────────────────────

def _violation(*, rule: str, severity: str, detail: str,
               card: dict[str, Any], lane_name: str,
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Single point of construction so every rule emits the same shape.
    Callers downstream rely on these keys verbatim — adding new fields is
    fine, renaming existing ones requires sweeping the consumers."""
    out = {
        "card_id":   card.get("id", ""),
        "card_name": card.get("name", "(unnamed)"),
        "card_url":  card.get("shortUrl", ""),
        "board_id":  card.get("idBoard", ""),
        "list_id":   card.get("idList", ""),
        "lane":      lane_name or "",
        "rule":      rule,
        "severity":  severity,
        "detail":    detail,
    }
    if extra:
        out.update(extra)
    return out


# ── Rule implementations ───────────────────────────────────────────────────
# Each rule function takes a fully-loaded card dict (from get_card) plus
# the resolved lane_name, and returns a Violation dict OR None. Keeping
# them small + independent makes tests trivial and lets the GUI pull
# specific rules selectively if needed.

def rule_no_owner(card: dict[str, Any], lane_name: str) -> dict[str, Any] | None:
    if card.get("idMembers"):
        return None
    members = card.get("members") or []
    if any((m or {}).get("id") for m in members):
        return None
    desc_fields = _flatten_desc(card.get("desc"))
    for key in _DESC_OWNER_KEYS:
        if desc_fields.get(key):
            return None
    # Grace period: don't flag cards created in the last 3 days. Intake
    # usually assigns an owner during the first day or two — flagging a
    # card created this morning as "no owner" is noise. Trello card ids
    # encode creation time as the first 4 bytes of a Mongo ObjectId, so
    # this check is free (no extra API call).
    cid = card.get("id", "")
    if cid and len(cid) >= 8:
        try:
            ts = int(cid[:8], 16)
            age_days = (_dt.datetime.now(_dt.timezone.utc).timestamp()
                          - ts) / 86400
            if age_days < 3:
                return None
        except (ValueError, OSError):
            pass
    return _violation(
        rule="no_owner", severity="warn",
        detail="No assigned member or Owner field in description.",
        card=card, lane_name=lane_name,
    )


def rule_no_follow_up(card: dict[str, Any], lane_name: str) -> dict[str, Any] | None:
    """Card has no Trello due date set. Closed/parked lanes don't need one."""
    if _is_parked_lane(lane_name):
        return None
    if card.get("due"):
        return None
    return _violation(
        rule="no_follow_up", severity="warn",
        detail="No follow-up date set (Trello due date is empty).",
        card=card, lane_name=lane_name,
    )


def rule_no_next_action(card: dict[str, Any], lane_name: str) -> dict[str, Any] | None:
    """Last comment must hint at the next step. We accept either an
    explicit `Next:` line in the card desc OR a recent comment that
    contains @mention / next: / handoff keywords / ≥ 60 chars."""
    if _is_parked_lane(lane_name):
        return None
    desc_fields = _flatten_desc(card.get("desc"))
    if any(desc_fields.get(k) for k in _NEXT_ACTION_KEYS):
        return None
    last = _last_comment(card)
    if last is None:
        # No comments at all → covered by stale_no_comment; skip the
        # double-flag here.
        return None
    text = ((last.get("data") or {}).get("text") or "").strip()
    if not text:
        return None
    if _HANDOFF_KEYWORDS_RE.search(text):
        return None
    if len(text) >= _HANDOFF_MIN_CHARS:
        return None
    return _violation(
        rule="no_next_action", severity="info",
        detail=("Latest comment is short and has no @mention or "
                "'next:' / 'handoff' marker."),
        card=card, lane_name=lane_name,
        extra={"last_comment": text[:120]},
    )


def rule_stale_no_comment(card: dict[str, Any], lane_name: str,
                           *, lane_overrides: dict[str, int] | None = None,
                           now: _dt.datetime | None = None
                           ) -> dict[str, Any] | None:
    """Card has gone N+ days without a new comment, where N is the lane's
    threshold. Parked lanes skipped."""
    if _is_parked_lane(lane_name):
        return None
    threshold = _stale_days_for_lane(lane_name, lane_overrides)
    last = _last_comment(card)
    last_iso = (last or {}).get("date") or card.get("dateLastActivity") or ""
    last_dt = _parse_iso(last_iso)
    if last_dt is None:
        # No usable timestamp → can't decide, don't flag (avoids
        # false positives on cards where Trello returned a malformed
        # action date).
        return None
    days = _days_between(now or _utcnow(), last_dt)
    if days is None or days < threshold:
        return None
    return _violation(
        rule="stale_no_comment", severity="warn",
        detail=(f"No new comment in {int(days)}d "
                f"(lane threshold {threshold}d)."),
        card=card, lane_name=lane_name,
        extra={"days_silent": int(days),
               "last_activity_iso": last_iso,
               "threshold_days": threshold},
    )


# Compiled once at module import for hot-loop reuse.
_COMPLAINT_COMPILED = tuple(
    (re.compile(pat, re.IGNORECASE), sev, label)
    for pat, sev, label in _COMPLAINT_PATTERNS
)


def rule_customer_complaint(card: dict[str, Any], lane_name: str,
                              *, now: _dt.datetime | None = None
                              ) -> dict[str, Any] | None:
    """Scan the card's comment stream for complaint / legal / escalation
    keywords. Returns the FIRST match found (newest-first), with the
    matched snippet attached so the GUI can show context without
    requiring the user to click into Trello.

    Includes parked lanes — a customer complaint that arrives on a
    closed job is precisely the case we want to surface, not suppress.
    """
    cutoff_dt = (now or _utcnow()) - _dt.timedelta(
        days=_COMPLAINT_LOOKBACK_DAYS)
    for action in card.get("actions") or []:
        if action.get("type") != "commentCard":
            continue
        a_dt = _parse_iso(action.get("date") or "")
        if a_dt is not None and a_dt < cutoff_dt:
            # Comments are newest-first; once we cross the cutoff,
            # everything older won't match either.
            break
        text = ((action.get("data") or {}).get("text") or "")
        if not text:
            continue
        for regex, severity, label in _COMPLAINT_COMPILED:
            m = regex.search(text)
            if not m:
                continue
            # Build a small snippet centered on the match so the row
            # gives instant context.
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 60)
            snippet = text[start:end].replace("\n", " ").strip()
            if start > 0:
                snippet = "…" + snippet
            if end < len(text):
                snippet = snippet + "…"
            return _violation(
                rule="customer_complaint", severity=severity,
                detail=f"[{label}] {snippet[:_COMPLAINT_SNIPPET_CHARS]}",
                card=card, lane_name=lane_name,
                extra={
                    "matched":     m.group(0),
                    "label":       label,
                    "comment_iso": action.get("date") or "",
                    "author":      ((action.get("memberCreator") or {})
                                    .get("fullName") or ""),
                },
            )
    return None


# Customer chose a competitor / declined our proposal — the phrasing that
# loses a job. Only the competitor/decline subset (not "no charge" / generic
# cancel) so the nudge specifically means "close out a lost bid".
_LOST_JOB_RE = re.compile(
    r'another\s+(?:firm|company|contractor|vendor|restoration)|'
    r'(?:went|going|mov(?:ed|ing)\s+(?:ahead|forward))\s+with\s+another|'
    r'declined\s+(?:our|the)\s+(?:proposal|estimate)', re.IGNORECASE)


def rule_lost_job(card: dict[str, Any], lane_name: str) -> dict[str, Any] | None:
    """OPEN card whose comments say the customer went with another firm —
    nudge to close it out. Closed/archived lost jobs are already handled by
    the Snapshots routing; this catches the one still sitting in a working
    lane after the 'no'."""
    if card.get("closed"):
        return None
    for action in card.get("actions") or []:
        if action.get("type") != "commentCard":
            continue
        text = ((action.get("data") or {}).get("text") or "")
        m = _LOST_JOB_RE.search(text)
        if m:
            return _violation(
                rule="lost_job", severity="warn",
                detail="Customer went with another firm — close this job out",
                card=card, lane_name=lane_name,
                extra={"matched": m.group(0),
                       "comment_iso": action.get("date") or ""})
    return None


def rule_equipment_on_site(card: dict[str, Any],
                           lane_name: str) -> dict[str, Any] | None:
    """OPEN card with equipment placed and no pickup logged for 3+ days —
    rental/loss risk. Uses the same eq_lifecycle detection as the audit
    Job-log button, on the card's inline comment stream."""
    if card.get("closed"):
        return None
    try:
        import snapshot_logic as _sl
    except Exception:
        return None
    comments = [a for a in (card.get("actions") or [])
                if a.get("type") == "commentCard"]
    try:
        eq = _sl.eq_lifecycle(comments)
    except Exception:
        return None
    if not eq.get("outstanding"):
        return None
    d = eq.get("days_out")
    if d is not None and d < 3:
        return None   # too fresh to nag
    detail = ("Equipment still on site"
              + (f" ({d}d)" if d else "")
              + f" — placed {', '.join(eq.get('placed') or [])}, no pickup logged")
    return _violation(
        rule="equipment_on_site", severity="warn", detail=detail,
        card=card, lane_name=lane_name,
        extra={"days_out": d, "placed": eq.get("placed") or []})


# Order matters for display only — first violation per card is the one
# the GUI's count badge highlights. Severity sort is applied separately
# in scan_card so the most actionable rule wins regardless of order here.
_CARD_RULES = (
    rule_no_owner,
    rule_no_follow_up,
    rule_stale_no_comment,
    rule_no_next_action,
    rule_customer_complaint,
    rule_lost_job,
    rule_equipment_on_site,
)


def scan_card(card: dict[str, Any], *, lane_name: str = "",
              lane_overrides: dict[str, int] | None = None,
              now: _dt.datetime | None = None) -> list[dict[str, Any]]:
    """Run every per-card rule and return the violations found.

    `card` must be the dict returned by `trello_client.get_card` — it
    needs members, idMembers, desc, due, dateLastActivity, plus the
    inline `actions` list. Skipping any of those would defeat specific
    rules (e.g. members are required for owner detection).
    """
    if not card:
        return []
    out: list[dict[str, Any]] = []
    for fn in _CARD_RULES:
        try:
            if fn is rule_stale_no_comment:
                v = fn(card, lane_name,
                       lane_overrides=lane_overrides, now=now)
            elif fn is rule_customer_complaint:
                v = fn(card, lane_name, now=now)
            else:
                v = fn(card, lane_name)
        except Exception:
            # One bad rule shouldn't poison the whole scan. We log via
            # ems_log when wired into the GUI; here we just swallow so
            # tests stay deterministic without a logger.
            v = None
        if v:
            out.append(v)
    return out


# ── Lane-move handoff scan (rule B) ────────────────────────────────────────
# Different shape from per-card rules because this one walks the action
# stream of recently-moved cards. We don't rely on `dateLastActivity`
# alone — that bumps for any edit, masking moves that happened earlier
# in the day.

def is_handoff_comment(text: str) -> bool:
    """True when a comment looks like a real handoff note. Used both by
    the lane-move scan and by rule_no_next_action so the heuristic stays
    in one place."""
    if not text:
        return False
    if _HANDOFF_KEYWORDS_RE.search(text):
        return True
    return len(text.strip()) >= _HANDOFF_MIN_CHARS


def scan_card_lane_move(card: dict[str, Any], *, lane_name: str = "",
                         hours_back: int = 24,
                         now: _dt.datetime | None = None
                         ) -> dict[str, Any] | None:
    """If `card` moved lanes in the last `hours_back` hours, decide whether
    a proper handoff comment was left after the move.

    A "good" handoff is the most recent commentCard action whose timestamp
    is >= the lane-move timestamp AND whose text passes
    `is_handoff_comment`. Anything else (no comment after move, or a
    too-short generic comment) flags."""
    move = _last_lane_move(card)
    if move is None:
        return None
    move_dt = _parse_iso(move.get("date") or "")
    if move_dt is None:
        return None
    elapsed = _days_between(now or _utcnow(), move_dt)
    if elapsed is None or elapsed * 24 > hours_back:
        return None

    move_data = move.get("data") or {}
    list_after = (move_data.get("listAfter") or {}).get("name") or lane_name
    list_before = (move_data.get("listBefore") or {}).get("name") or "?"

    # Find the first comment AT OR AFTER the move.
    handoff_text = ""
    for a in card.get("actions") or []:
        if a.get("type") != "commentCard":
            continue
        c_dt = _parse_iso(a.get("date") or "")
        if c_dt is None or c_dt < move_dt:
            continue
        handoff_text = ((a.get("data") or {}).get("text") or "").strip()
        if handoff_text:
            break

    if is_handoff_comment(handoff_text):
        return None
    detail = (f"Moved {list_before} → {list_after} but "
              + ("no comment was left after the move."
                 if not handoff_text
                 else "post-move comment is too short / has no marker."))
    return _violation(
        rule="lane_move_no_handoff", severity="warn",
        detail=detail,
        card=card, lane_name=list_after,
        extra={
            "moved_from":     list_before,
            "moved_to":       list_after,
            "moved_at_iso":   move.get("date") or "",
            "post_move_text": handoff_text[:120],
        },
    )


# ── Email-source complaint scan ────────────────────────────────────────────
# Customers usually complain via EMAIL to EMS@servpro10100, not by editing a
# Trello card. So the hygiene scan looks at both surfaces — Trello card
# comments (rule_customer_complaint above) AND inbox messages here.
# Both produce the same Violation shape so the GUI can render them in the
# same Customer concerns section with a small chip distinguishing source.

def scan_inbox_for_complaints(*, days: int = 14,
                               top: int = 200) -> list[dict[str, Any]]:
    """Scan recent inbox messages with the complaint regex set. Each
    matching message is returned as a Violation dict; when the message
    can be matched to a Trello card via adjuster_monitor.match_email_to_card,
    the card_id/card_name/card_url fields are populated so the row can
    open the right Trello card directly. Otherwise card_* fields are
    empty and the row is treated as "unrouted" (still flagged, just
    without a click-through to a specific job).

    Reads via `outlook_local` (Outlook desktop COM). Returns [] silently
    when Outlook isn't running or pywin32 is missing — keeps the
    hygiene scan working without hard-failing the panel.
    """
    try:
        import outlook_local as ol
    except Exception:
        return []
    try:
        since = _utcnow() - _dt.timedelta(days=days)
        messages = ol.list_recent_messages(since=since, top=top)
    except Exception:
        return []

    # Local import to avoid a cycle: adjuster_monitor imports
    # trello_client which is fine, but this module pulling in
    # adjuster_monitor at import time would circle back if anything
    # else later imports trello_hygiene during adjuster_monitor's import.
    try:
        import adjuster_monitor as am
    except Exception:
        am = None

    out: list[dict[str, Any]] = []
    for m in messages:
        sender = ((m.get("from") or {}).get("emailAddress") or {})
        sender_addr = (sender.get("address") or "")
        # Skip internal mail — staff replies to each other shouldn't
        # be treated as customer complaints.
        if am is not None and am._looks_internal(sender_addr):
            continue
        subject = (m.get("subject") or "")
        preview = (m.get("bodyPreview") or "")
        text = f"{subject}\n{preview}"
        if not text.strip():
            continue
        match = None
        match_label = ""
        hit_severity = ""
        _sev_rank = {"error": 2, "warn": 1}
        for regex, severity, label in _COMPLAINT_COMPILED:
            mm = regex.search(text)
            if not mm:
                continue
            # Prefer the HIGHEST-severity match, not the first. The warn
            # "complaint" patterns are listed before the error legal/
            # lawsuit/BBB ones, so first-match-wins mislabeled an email
            # that mentioned both as merely warn — under-prioritizing the
            # legal escalation.
            if (match is None
                    or _sev_rank.get(severity, 0) > _sev_rank.get(hit_severity, 0)):
                match = mm
                match_label = label
                hit_severity = severity
                if _sev_rank.get(severity, 0) >= 2:
                    break   # error is the max severity — no need to look further
        if match is None:
            continue
        # Build a small snippet around the matched phrase for context.
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 60)
        snippet = text[start:end].replace("\n", " ").strip()
        if start > 0: snippet = "…" + snippet
        if end < len(text): snippet = snippet + "…"

        # Try to route to a Trello card. Unrouted hits are still
        # surfaced so the user sees the concern; they just don't get
        # a card link.
        card = None
        if am is not None:
            try:
                card = am.match_email_to_card(m)
            except Exception:
                card = None

        sender_name = (sender.get("name") or "").strip() or sender_addr
        received = (m.get("receivedDateTime") or "")[:16].replace("T", " ")
        out.append({
            "card_id":   (card or {}).get("id", ""),
            "card_name": ((card or {}).get("name", "")
                          or f"📧 {sender_name}"),
            "card_url":  (card or {}).get("shortUrl", ""),
            "board_id":  (card or {}).get("idBoard", ""),
            "list_id":   (card or {}).get("idList", ""),
            "lane":      (card or {}).get("_match_reason", "")
                          if card else "Inbox",
            "rule":      "customer_complaint",
            "severity":  hit_severity,
            "detail":    f"[{match_label}] {snippet[:_COMPLAINT_SNIPPET_CHARS]}",
            "source":    "email",
            "matched":   match.group(0),
            "label":     match_label,
            "email_id":  m.get("id", ""),
            "email_link": m.get("webLink", ""),
            "email_from": sender_addr,
            "email_subject": subject,
            "email_received": received,
        })
    return out


# ── Workspace-wide scan ────────────────────────────────────────────────────

def _iter_all_cards(*, max_per_board: int,
                     enum_cb=None) -> list[dict[str, Any]]:
    """Walk every in-scope board, every open list, return shallow card
    summaries. The follow-up `get_card` call adds the heavyweight fields
    (members, actions) per card we actually scan — no point paying for
    those on cards we'd skip anyway.

    `enum_cb(label)` is called once per board enumerated so callers can
    display "Listing board: WIP (3/8)" while the (rate-limited)
    boards/lists/cards walks happen — otherwise the GUI shows a frozen
    'Enumerating…' message for the first 5-10 seconds.
    """
    out: list[dict[str, Any]] = []
    # exclude_quality=True drops the AR / billing boards centrally —
    # see trello_client.QUALITY_EXCLUDED_BOARD_NAMES. ar_followup's XA
    # apology scan still calls list_boards() without the flag so it
    # keeps seeing the AR board.
    boards = tc.list_boards(exclude_quality=True) or []
    n = len(boards)
    for idx, b in enumerate(boards, start=1):
        if enum_cb is not None:
            try:
                enum_cb(f"Listing board {idx}/{n}: {b.get('name', '')}")
            except Exception:
                pass
        try:
            lists = tc._call(
                f"/boards/{b['id']}/lists",
                params={"fields": "id,name", "filter": "open"},
            ) or []
        except Exception:
            continue
        for lst in lists:
            try:
                cards = tc.cards_in_list(
                    lst.get("id"),
                    fields="id,name,shortUrl,idBoard,idList,closed,"
                            "idMembers,due,dateLastActivity",
                ) or []
            except Exception:
                continue
            for c in cards[:max_per_board]:
                c["_board_name"] = b.get("name", "")
                c["_list_name"]  = lst.get("name", "")
                out.append(c)
                # Piggyback: keep the Pipeline lifecycle table fresh
                # without forcing the user to click ↻ Sync. Cheap (one
                # DB upsert per card, zero extra Trello calls). Wrapped
                # in try/except so a pipeline DB issue never breaks
                # the Hygiene scan that owns this loop.
                try:
                    import pipeline_stages as _ps
                    _ps.upsert_card(c)
                except Exception:
                    pass
    return out


def scan_workspace(*, max_per_list: int = 200,
                    lane_overrides: dict[str, int] | None = None,
                    include_hygiene: bool = True,
                    include_handoff: bool = True,
                    include_closeout: bool = True,
                    include_xa_gaps: bool = True,
                    include_ipr: bool = True,
                    closeout_lookback_days: int = 30,
                    xa_lookback_days: int = 60,
                    ipr_lookback_days: int = 14,
                    progress_cb=None) -> dict[str, list[dict[str, Any]]]:
    """One-pass scan that produces hygiene violations AND closeout
    candidates AND XA-note gaps. Single get_card call per card; XA
    ingest runs once at the end against a separate Outlook pull.

    Returns: {"hygiene": [...], "closeout": [...], "xa_gaps": [...]}.
    `progress_cb(done, total, name)` is invoked after each card so the
    GUI can paint a determinate progress bar.

    Earlier versions called `scan_all_in_scope` AND
    `closeout_watcher.find_snapshot_candidates` back-to-back; that ran
    the (rate-limited) get_card fetch twice per card and roughly
    doubled total wall time. This consolidates both rule sets onto the
    same payload — same data, half the API cost.
    """
    import closeout_watcher as cw  # local import to avoid module-load cycle
    import ipr_tracker as ipr  # same — avoid module-load cycle on init

    # Pull the authenticated user's profile once so the IPR scan can
    # match @mentions against username + display name. None when Trello
    # creds aren't configured; ipr.scan_card_for_iprs no-ops on that.
    me = None
    my_username = ""
    my_full_name = ""
    if include_ipr:
        try:
            me = tc.get_member_me() or None
            if me:
                my_username = (me.get("username") or "").strip()
                my_full_name = (me.get("fullName") or "").strip()
        except Exception:
            me = None
        if not my_username:
            include_ipr = False

    # progress_cb is also fired during enumeration with done=0, total=0
    # and `name` carrying the phase label. Callers that only want
    # per-card progress can ignore those (their fmt is "0/0 · label · ETA")
    # or special-case `total == 0`. Hygiene GUI uses the latter to keep
    # the progress bar at zero while the label updates.
    def _enum(label):
        if progress_cb is not None:
            try:
                progress_cb(0, 0, label)
            except Exception:
                pass

    summaries = _iter_all_cards(
        max_per_board=max_per_list, enum_cb=_enum)

    # Activity prefilter: drop parked-lane cards that have been quiet
    # for >90 days. They never produce actionable hygiene results
    # (parked-lane suppression covers the time-based rules; no_owner
    # on a 2-year-old closed job isn't useful) and skipping them saves
    # one Trello round-trip per card. Lane-based closeout candidates
    # are unaffected — those came from cards_in_list, not summaries.
    cutoff = _utcnow() - _dt.timedelta(days=_PREFILTER_PARKED_AGE_DAYS)
    pre_count = len(summaries)
    filtered: list[dict[str, Any]] = []
    for s in summaries:
        lane = s.get("_list_name", "")
        if not _is_parked_lane(lane):
            filtered.append(s)
            continue
        last_dt = _parse_iso(s.get("dateLastActivity") or "")
        if last_dt is None or last_dt >= cutoff:
            # Recently active despite the parked lane — keep so we
            # don't miss cards a user is rescuing back into active work.
            filtered.append(s)
    summaries = filtered
    skipped = pre_count - len(summaries)
    if skipped and progress_cb is not None:
        try:
            progress_cb(0, 0,
                        f"Prefilter dropped {skipped} stale parked-lane "
                        f"cards. Scanning {len(summaries)} cards…")
        except Exception:
            pass

    total = len(summaries)
    hygiene: list[dict[str, Any]] = []
    closeouts: list[dict[str, Any]] = []
    drafted = {}
    existing_pdf_keys: set[str] = set()
    if include_closeout:
        try:
            import persistence as per
            drafted = per.get("closeout_drafted") or {}
            if not isinstance(drafted, dict):
                drafted = {}
        except Exception:
            drafted = {}
        # Skip cards whose snapshot PDF already exists on disk — covers
        # legacy jobs that were snapshotted before mark_drafted was
        # auto-wired into the snapshot-success path. Cheap (one scandir
        # over snapshot_output).
        try:
            existing_pdf_keys = cw._existing_snapshot_pdf_names()
        except Exception:
            existing_pdf_keys = set()

    def _is_already_snapshotted(card_dict) -> bool:
        if not existing_pdf_keys:
            return False
        try:
            return (cw._canon_pdf_key(card_dict.get("card_name", ""))
                     in existing_pdf_keys)
        except Exception:
            return False

    # Lane-based closeout candidates first — they're cheap (one
    # cards_in_list call) and don't require a per-card fetch. Filtered
    # against `drafted` + existing on-disk PDFs here so the GUI never
    # sees already-handled cards.
    if include_closeout:
        for c in cw.find_lane_candidates():
            if c["card_id"] in drafted:
                continue
            if _is_already_snapshotted(c):
                continue
            closeouts.append(c)
    seen_closeout = {c["card_id"] for c in closeouts}
    closeout_since = (_utcnow() - _dt.timedelta(days=closeout_lookback_days)
                      if include_closeout else None)

    iprs: list[dict[str, Any]] = []
    now = _utcnow()
    for i, s in enumerate(summaries, start=1):
        cid = s.get("id")
        if not cid:
            continue
        try:
            card = tc.get_card(cid, actions_limit=50)
        except Exception:
            card = None
        if card is not None:
            lane = s.get("_list_name", "")
            # Carry the board name onto the card for IPR rows — the GUI
            # groups by board in its filter dropdown and the per-card
            # fetch doesn't echo `_board_name` back from the summary.
            if "_board_name" in s and "_board_name" not in card:
                card["_board_name"] = s.get("_board_name", "")
            if include_hygiene:
                hygiene.extend(scan_card(
                    card, lane_name=lane,
                    lane_overrides=lane_overrides, now=now))
            if include_handoff:
                v = scan_card_lane_move(card, lane_name=lane, now=now)
                if v:
                    hygiene.append(v)
            if include_ipr:
                iprs.extend(ipr.scan_card_for_iprs(
                    card, lane_name=lane,
                    my_username=my_username,
                    my_full_name=my_full_name,
                    lookback_days=ipr_lookback_days,
                    now=now))
            if (include_closeout and cid not in seen_closeout
                    and cid not in drafted):
                match = cw._matching_comment(card, since=closeout_since)
                if match is not None:
                    cand = cw._candidate_card(
                        card, source="comment",
                        trigger_iso=match.get("date") or "",
                        trigger_text=((match.get("data") or {}).get("text")
                                      or ""),
                        lane_name=lane,
                    )
                    # Same on-disk PDF check as the lane path — a card
                    # whose snapshot already exists shouldn't surface
                    # via the comment signal either.
                    if not _is_already_snapshotted(cand):
                        closeouts.append(cand)
                        seen_closeout.add(cid)
        if progress_cb is not None:
            try:
                name = (card or s).get("name", "") if card else s.get("name", "")
                progress_cb(i, total, name)
            except Exception:
                pass
    # Email-source complaint scan tacked on at the end. Best-effort:
    # if Graph isn't configured, scan_inbox_for_complaints returns []
    # silently and the result set is unchanged. Surfacing it through
    # the same `hygiene` list (keyed by rule="customer_complaint") means
    # the GUI splitter at _scan_finished routes Trello + email matches
    # into the same Customer concerns section.
    if include_hygiene:
        if progress_cb is not None:
            try: progress_cb(0, 0, "Scanning inbox for complaints…")
            except Exception: pass
        try:
            hygiene.extend(scan_inbox_for_complaints())
        except Exception as ex:
            # Best-effort: a Graph/Outlook hiccup shouldn't abort the
            # whole scan. Log so the user can see the cause if the
            # complaint section comes back empty unexpectedly.
            try:
                import ems_log
                ems_log.warn("hygiene", f"complaint scan failed: {ex}")
            except Exception:
                pass

    # XA-note gap ingest. Walks the same inbox the complaint scan uses;
    # filters to staff-→-carrier mail; groups by claim# / insured; runs
    # gap analysis. Returns [] silently when Graph isn't configured so
    # the rest of the scan still works on machines without Azure setup.
    xa_gaps: list[dict[str, Any]] = []
    if include_xa_gaps:
        if progress_cb is not None:
            try: progress_cb(0, 0, "Scanning inbox for XA notes…")
            except Exception: pass
        try:
            import xa_email_ingest as xei
            xa_result = xei.scan_inbox(
                days=xa_lookback_days, progress_cb=None)
            xa_gaps = xei.filter_unresolved(xa_result.get("groups") or [])
        except Exception as ex:
            xa_gaps = []
            try:
                import ems_log
                ems_log.warn("hygiene", f"XA gap ingest failed: {ex}")
            except Exception:
                pass

    # Drop already-resolved IPR rows so the GUI doesn't even see them.
    # `ipr_resolved` keys are `card_id::comment_id`; persistence layer
    # owns the schema, we just consult it here.
    if include_ipr and iprs:
        try:
            import persistence as per
            resolved = set()
            stored = per.get("ipr_resolved") or {}
            if isinstance(stored, dict):
                resolved = set(stored.keys())
            iprs = [
                r for r in iprs
                if f"{r.get('card_id', '')}::{r.get('comment_id', '')}"
                   not in resolved
            ]
        except Exception:
            pass

    return {"hygiene": hygiene, "closeout": closeouts,
            "xa_gaps": xa_gaps, "ipr": iprs}


def scan_all_in_scope(*, max_per_board: int = 200,
                      lane_overrides: dict[str, int] | None = None,
                      include_handoff: bool = True,
                      progress_cb=None) -> list[dict[str, Any]]:
    """Run the full hygiene scan across every in-scope board.

    For each card found via the lightweight enumeration we issue a single
    `get_card` to pull members + last-50 actions + due — the same payload
    the rules need. Per-card rules + (optionally) the lane-move rule are
    applied; results are concatenated.

    `progress_cb(done, total, current_card_name)` is invoked after each
    card so a GUI can paint a progress bar. Pass None for headless / CLI.

    Errors on individual cards are swallowed (logged when the wiring
    layer hooks ems_log) so one rate-limited card doesn't abort the
    whole sweep.
    """
    summaries = _iter_all_cards(max_per_board=max_per_board)
    total = len(summaries)
    out: list[dict[str, Any]] = []
    now = _utcnow()
    for i, s in enumerate(summaries, start=1):
        cid = s.get("id")
        if not cid:
            continue
        try:
            card = tc.get_card(cid, actions_limit=50)
        except Exception:
            card = None
        if not card:
            continue
        # Preserve the lightweight enumeration's lane / board names —
        # get_card() returns ids, not display strings, and we'd otherwise
        # have to round-trip the lists endpoint per rule.
        lane = s.get("_list_name", "")
        out.extend(scan_card(card, lane_name=lane,
                              lane_overrides=lane_overrides, now=now))
        if include_handoff:
            v = scan_card_lane_move(card, lane_name=lane, now=now)
            if v:
                out.append(v)
        if progress_cb is not None:
            try:
                progress_cb(i, total, card.get("name", ""))
            except Exception:
                pass
    return out


# ── CLI smoke test ─────────────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python trello_hygiene.py scan [--max=N]")
        print("  python trello_hygiene.py card <card_id_or_url>")
        return 1
    cmd = argv[0]
    if cmd == "scan":
        max_per_board = 200
        for a in argv[1:]:
            if a.startswith("--max="):
                try:
                    max_per_board = int(a.split("=", 1)[1])
                except ValueError:
                    pass

        def _progress(done, total, name):
            print(f"  [{done}/{total}] {name[:60]}")

        violations = scan_all_in_scope(
            max_per_board=max_per_board, progress_cb=_progress)
        print()
        if not violations:
            print("✓ No hygiene violations found.")
            return 0
        # Group by card_id for a tidier dump.
        by_card: dict[str, list[dict[str, Any]]] = {}
        for v in violations:
            by_card.setdefault(v["card_id"], []).append(v)
        for cid, vs in by_card.items():
            head = vs[0]
            print(f"[{head['lane']}]  {head['card_name']}")
            print(f"  {head['card_url']}")
            for v in vs:
                print(f"  · {v['rule']:24s} {v['detail']}")
            print()
        print(f"{len(violations)} violation(s) across {len(by_card)} card(s).")
        return 0
    if cmd == "card":
        if len(argv) < 2:
            print("Usage: python trello_hygiene.py card <card_id_or_url>")
            return 1
        cid = tc.parse_card_identifier(argv[1]) or argv[1]
        card = tc.get_card(cid, actions_limit=50)
        if not card:
            print(f"Card not found: {cid}")
            return 1
        lane = tc.get_lane_name(card.get("idBoard"), card.get("idList"))
        vs = scan_card(card, lane_name=lane)
        v_lm = scan_card_lane_move(card, lane_name=lane)
        if v_lm:
            vs.append(v_lm)
        print(f"Card:  {card.get('name', '')}")
        print(f"Lane:  {lane}")
        print(f"URL:   {card.get('shortUrl', '')}")
        if not vs:
            print("✓ No violations.")
            return 0
        for v in vs:
            print(f"  · {v['rule']:24s} {v['detail']}")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
