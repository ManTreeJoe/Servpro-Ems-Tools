"""Initial Photo Report (IPR) request tracker.

Pure logic, no UI. Detects Trello card comments where someone tags the
authenticated user AND the comment requests an Initial Photo Report.
Surfaced through the Hygiene panel so the user has a running list of
"techs/estimators are waiting on me to generate an IPR" instead of
relying on email-style Trello notifications they routinely miss.

The scan is folded into `trello_hygiene.scan_workspace` — same per-card
fetch, no extra Trello round-trips. This module just owns the
keyword + @mention rules and the request-row formatting.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any


# Default lookback for IPR comment detection. Anything older is assumed
# already actioned (or stale enough that the requester would have nudged
# again). 14 days covers a slow week + buffer.
DEFAULT_LOOKBACK_DAYS = 14

# Phrases that, when seen in a comment that ALSO @mentions the user,
# count as an IPR request. Tight enough to avoid false hits on generic
# "send photos" comments — those aren't asking for the formal report
# document, just the raw images.
_IPR_KEYWORD_RE = re.compile(
    r"\b(?:"
    r"initial\s+photo\s+report|"
    r"initial\s+report|"
    r"photo\s+report|"
    r"\bIPR\b|"
    r"photo\s+summary"
    r")\b",
    re.IGNORECASE,
)

# User's own follow-up comment that signals "I did the IPR" — we look
# for an action verb + an IPR-ish target. Matches the workflow the user
# described: pull photos from WC/SP → load into Xactimate → download
# the report → comment "uploaded" on the Trello card. Once a comment
# matching this pattern appears AFTER the request comment, the request
# auto-resolves so the panel doesn't keep nagging.
_IPR_COMPLETION_RE = re.compile(
    r"\b(?:"
    r"upload(?:ed|ing)?|"
    r"posted|"
    r"sent|"
    r"complete[d]?|"
    r"done|"
    r"finished|"
    r"attached"
    r")\b",
    re.IGNORECASE,
)


def _parse_iso(iso: str) -> _dt.datetime | None:
    if not iso:
        return None
    try:
        s = iso.split(".")[0].rstrip("Z")
        return _dt.datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _mentions_user(text: str, *, my_username: str,
                    my_full_name: str = "") -> bool:
    """True when `text` contains a Trello-style @mention of the user.

    Trello @mentions render as `@username` in the saved comment text.
    Some clients also write `@Full Name` (no link); accept that as
    a fallback when a full name is provided. Username match is
    case-insensitive (Trello usernames are lowercase but users type
    whatever)."""
    if not text:
        return False
    if my_username:
        # Match "@username" with a trailing word-boundary so
        # "@nathanbupte2" doesn't false-match "@nathanbupte". Leading
        # `@` is sufficient — false positives like "email@user" are
        # contrived in restoration-job comments.
        if re.search(rf"@{re.escape(my_username)}\b", text, re.IGNORECASE):
            return True
    if my_full_name:
        # Display-name @mentions (not a real Trello mention but
        # estimators sometimes write them by hand). Require @ + the
        # full name verbatim with word-boundary on both sides.
        if re.search(rf"@{re.escape(my_full_name)}\b", text, re.IGNORECASE):
            return True
    return False


def _is_ipr_comment(text: str) -> bool:
    """True when the comment text mentions an Initial Photo Report
    (or a clear synonym). Independent of the @mention check — the GUI
    composes both signals."""
    if not text:
        return False
    return _IPR_KEYWORD_RE.search(text) is not None


def _snippet(text: str, *, max_chars: int = 160) -> str:
    """Compact one-line preview of the matched comment for the row.
    Collapses whitespace; truncates with ellipsis."""
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) > max_chars:
        return flat[:max_chars - 1] + "…"
    return flat


def _request_row(card: dict[str, Any], action: dict[str, Any],
                  *, lane_name: str) -> dict[str, Any]:
    """Build one IPR request row from a card + a matching commentCard
    action. Same shape conventions as trello_hygiene._violation so the
    Hygiene panel can render rows uniformly."""
    data = action.get("data") or {}
    creator = action.get("memberCreator") or {}
    text = data.get("text") or ""
    return {
        "card_id":      card.get("id", ""),
        "card_name":    card.get("name", "(unnamed)"),
        "card_url":     card.get("shortUrl", ""),
        "board_id":     card.get("idBoard", ""),
        "board_name":   card.get("_board_name", ""),
        "list_id":      card.get("idList", ""),
        "lane_name":    lane_name or "",
        "comment_id":   action.get("id", ""),
        "comment_text": text,
        "snippet":      _snippet(text),
        "requested_by": (creator.get("fullName")
                          or creator.get("username")
                          or ""),
        "requested_at": action.get("date") or "",
        "rule":         "ipr_request",
        "severity":     "warn",
    }


def _user_completion_after(card: dict[str, Any], *, my_username: str,
                            after_iso: str) -> dict[str, Any] | None:
    """Return the user's first completion-style comment posted AFTER the
    request comment, or None. Walks the card's bundled actions stream
    newest-first; we want the EARLIEST completion (so a single follow-
    up clears the request even if the user kept commenting). Auto-
    resolution only fires when both the IPR keyword AND a completion
    verb appear in the same user comment — protects against an unrelated
    "uploaded the scope" comment clearing a pending IPR request."""
    after_dt = _parse_iso(after_iso)
    if after_dt is None or not my_username:
        return None
    matches: list[dict[str, Any]] = []
    for a in card.get("actions") or []:
        if a.get("type") != "commentCard":
            continue
        creator = a.get("memberCreator") or {}
        if (creator.get("username") or "").lower() != my_username.lower():
            continue
        when = _parse_iso(a.get("date") or "")
        if when is None or when <= after_dt:
            continue
        text = (a.get("data") or {}).get("text") or ""
        if not _IPR_COMPLETION_RE.search(text):
            continue
        if not _is_ipr_comment(text):
            # Some completion comments don't repeat the keyword
            # ("Uploaded just now"). Accept those too — the user wrote
            # them on the SAME card AFTER the IPR request, so context
            # is sufficient. Only require the IPR keyword when the
            # completion verb is itself ambiguous like "done".
            if re.search(r"\b(?:done|complete[d]?)\b", text, re.IGNORECASE):
                continue
        matches.append(a)
    if not matches:
        return None
    # actions are newest-first; pick the OLDEST match (earliest
    # post-request completion) so the resolve timestamp is accurate.
    return matches[-1]


def scan_card_for_iprs(card: dict[str, Any], *, lane_name: str,
                       my_username: str, my_full_name: str = "",
                       lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                       now: _dt.datetime | None = None
                       ) -> list[dict[str, Any]]:
    """Return one IPR request row per matching comment on this card.

    Rules per comment:
      • Type is `commentCard` and posted within the lookback window.
      • Comment author is NOT the user (otherwise the user's own posts
        would shadow as requests to themselves).
      • Comment @mentions the user.
      • Comment text matches an IPR keyword.
      • The user has NOT posted a completion-style comment AFTER it
        (e.g. "uploaded", "report posted") — those auto-resolve the
        request implicitly so the panel doesn't keep nagging once the
        work is done.

    Multiple unresolved matches on the same card produce multiple rows
    so the user can resolve each request independently — same handling
    as the customer-complaint scan."""
    if not card or not my_username:
        return []
    if now is None:
        now = _utcnow()
    cutoff = now - _dt.timedelta(days=max(1, int(lookback_days)))
    out: list[dict[str, Any]] = []
    for a in card.get("actions") or []:
        if a.get("type") != "commentCard":
            continue
        when = _parse_iso(a.get("date") or "")
        if when is not None and when < cutoff:
            continue
        creator = a.get("memberCreator") or {}
        if (creator.get("username") or "").lower() == my_username.lower():
            continue
        text = (a.get("data") or {}).get("text") or ""
        if not _is_ipr_comment(text):
            continue
        if not _mentions_user(text, my_username=my_username,
                               my_full_name=my_full_name):
            continue
        # Auto-resolve via the user's later "uploaded / done" comment.
        if _user_completion_after(card, my_username=my_username,
                                    after_iso=a.get("date") or ""):
            continue
        out.append(_request_row(card, a, lane_name=lane_name))
    return out


def filter_unresolved(rows: list[dict[str, Any]],
                       resolved_ids: set[str] | None) -> list[dict[str, Any]]:
    """Drop rows whose `comment_id` appears in the resolved set.
    Resolved IPRs persist across sessions via persistence; the GUI
    passes this set in so the cached scan never re-surfaces them."""
    if not resolved_ids:
        return list(rows)
    return [r for r in rows
            if r.get("comment_id") and r["comment_id"] not in resolved_ids]
