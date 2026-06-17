"""AR Board → XactAnalysis worklist generator.

The standard apology note ("Our apologies for the delay…") needs to be
added in **XactAnalysis**, not on the Trello card — XA is the system of
record for adjuster-facing communication on AR cards. XA isn't
scriptable from this suite (no API access), so this module's job is
purely **discovery + reminder**:

    1. Find AR Board cards that have been silent for `stale_days` days.
    2. Skip cards the user already marked as handled within the cooldown.
    3. Surface them in the Hygiene panel's 🔔 XA reminders section.
    4. User opens each card in Trello to grab the carrier/claim/adjuster
       details, posts the apology in XA, then clicks "Done" — which
       calls mark_handled() and the row disappears for cooldown_days.

Public API:
    find_stale_cards(stale_days=7, cooldown_days=6) -> [{...}]
    mark_handled(card_id)
    was_handled_recently(card_id, cooldown_days=6) -> bool
    clear_history()
    DEFAULT_NOTE  — the apology text the user should paste into XA

Replaces the previous "auto-post to Trello" behavior, which was wrong:
posting on Trello doesn't deliver the message to adjusters; only XA
does.
"""
from __future__ import annotations

import datetime as _dt
import sys
from typing import Any

import persistence as per
import trello_client as tc


AR_BOARD_NAME = "AR BOARD"

# The apology text to paste into XA. Same wording the paused Power
# Automate flow used and the user has typed manually for years —
# centralizing it here so the GUI can show it next to a "Copy" button.
DEFAULT_NOTE = (
    "Our apologies for the delay. Please note our estimating team is "
    "diligently working on the file."
)

DEFAULT_STALE_DAYS = 7
DEFAULT_COOLDOWN_DAYS = 6   # ~weekly cycle


# ── Helpers ──────────────────────────────────────────────────────────────

def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _ar_board_id() -> str | None:
    """Resolve AR_BOARD_NAME to a board id once. Returns None when the
    workspace doesn't have an AR board (or trello is misconfigured).
    Match is case-insensitive substring so renames like 'AR Board (2026)'
    still match without an admin patch."""
    try:
        boards = tc.list_boards() or []
    except Exception:
        return None
    target = AR_BOARD_NAME.lower()
    for b in boards:
        if target in (b.get("name") or "").lower():
            return b.get("id")
    return None


def _last_comment_iso(card_actions: list[dict]) -> str:
    """Newest commentCard date in ISO form, or empty string when the
    card has no comments in the inline action window."""
    for a in card_actions or []:
        if a.get("type") == "commentCard":
            return a.get("date") or ""
    return ""


def was_handled_recently(card_id: str, *,
                          cooldown_days: int = DEFAULT_COOLDOWN_DAYS
                          ) -> bool:
    """True when the user clicked 'Done' on this card within the
    cooldown window. Persistence key was renamed from `ar_followup_posted`
    to `ar_xa_handled` so the legacy auto-posting history doesn't
    bleed into the new manual-handling flow — we want a clean cooldown
    after the workflow change."""
    history = per.get("ar_xa_handled") or {}
    if not isinstance(history, dict):
        return False
    last = history.get(card_id)
    last_dt = _parse_iso(last or "")
    if last_dt is None:
        return False
    return (_utcnow() - last_dt).days < cooldown_days


def mark_handled(card_id: str) -> None:
    """Record that the user added the apology in XA for this card. The
    Hygiene panel's row 'Done' button calls this so the card disappears
    from the worklist for cooldown_days."""
    if not card_id:
        return
    history = per.get("ar_xa_handled") or {}
    if not isinstance(history, dict):
        history = {}
    history[card_id] = _utcnow().isoformat(timespec="seconds")
    per.set_value("ar_xa_handled", history)


def clear_history() -> None:
    """Wipe the handled-flags map. Used when the user wants every card
    to re-surface (e.g. after a long absence + want to re-walk)."""
    per.set_value("ar_xa_handled", {})


# ── Public scan ──────────────────────────────────────────────────────────

def find_stale_cards(*, stale_days: int = DEFAULT_STALE_DAYS,
                      cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
                      progress_cb=None) -> list[dict[str, Any]]:
    """Cards on AR Board with no comment in `stale_days` days that the
    user hasn't already marked as handled-in-XA within `cooldown_days`.

    Returns dicts shaped like the Hygiene panel's other rows so the
    rendering layer can reuse the same row template:
        card_id, card_name, card_url, lane, last_comment_iso, days_silent
    """
    board_id = _ar_board_id()
    if not board_id:
        return []
    try:
        lists = tc._call(
            f"/boards/{board_id}/lists",
            params={"fields": "id,name", "filter": "open"},
        ) or []
    except Exception:
        return []

    cards_summary: list[tuple[dict, str]] = []
    for lst in lists:
        try:
            cs = tc.cards_in_list(
                lst.get("id"),
                fields="id,name,shortUrl,idBoard,idList,closed,"
                        "dateLastActivity") or []
        except Exception:
            continue
        for c in cs:
            cards_summary.append((c, lst.get("name", "")))

    cutoff = _utcnow() - _dt.timedelta(days=stale_days)
    out: list[dict[str, Any]] = []
    total = len(cards_summary)
    for i, (s, lane) in enumerate(cards_summary, start=1):
        cid = s.get("id")
        if not cid:
            continue
        if was_handled_recently(cid, cooldown_days=cooldown_days):
            continue
        try:
            card = tc.get_card(cid, actions_limit=10)
        except Exception:
            card = None
        if card is None:
            continue
        last_iso = _last_comment_iso(card.get("actions") or [])
        last_dt = _parse_iso(last_iso)
        if last_dt is not None and last_dt >= cutoff:
            if progress_cb is not None:
                try: progress_cb(i, total, card.get("name", ""))
                except Exception: pass
            continue
        days_silent = ((_utcnow() - last_dt).days
                        if last_dt is not None
                        else (stale_days + 1))
        out.append({
            "card_id":          cid,
            "card_name":        card.get("name", ""),
            "card_url":         card.get("shortUrl", ""),
            "lane":             lane,
            "last_comment_iso": last_iso,
            "days_silent":      days_silent,
            # Pull the XA assignment URL out of the card desc so the
            # Hygiene XA-apology row can render a direct "Open in XA"
            # button. Always a fresh-ish value because get_card just
            # ran a line above.
            "xa_link":          tc.card_xa_link(card),
        })
        if progress_cb is not None:
            try: progress_cb(i, total, card.get("name", ""))
            except Exception: pass
    return out


# ── CLI ──────────────────────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python ar_followup.py preview  [--days=N]")
        print("  python ar_followup.py mark <card_id>")
        print("  python ar_followup.py clear-history")
        print()
        print("Workflow: AR cards that go quiet need the apology note "
              "added in XactAnalysis (a manual step). 'preview' shows "
              "which cards are due. After you post in XA, run 'mark "
              "<card_id>' so the card stops re-surfacing for ~a week.")
        return 1
    cmd = argv[0]
    days = DEFAULT_STALE_DAYS
    for a in argv[1:]:
        if a.startswith("--days="):
            try: days = int(a.split("=", 1)[1])
            except ValueError: pass
    if cmd == "preview":
        cards = find_stale_cards(stale_days=days)
        if not cards:
            print(f"✓ No AR cards stale > {days} days "
                  f"(or no AR Board found / all marked handled).")
            return 0
        print(f"{len(cards)} AR card(s) needing the apology in XA:")
        print()
        for c in cards:
            last = c["last_comment_iso"][:10] or "never"
            print(f"  [{c['lane']}]  {c['card_name']}")
            print(f"    last comment: {last}  ({c['days_silent']}d silent)")
            print(f"    {c['card_url']}")
            print(f"    card_id:  {c['card_id']}")
        print()
        print("Standard note to paste in XA:")
        print(f"  > {DEFAULT_NOTE}")
        return 0
    if cmd == "mark":
        if len(argv) < 2:
            print("Usage: python ar_followup.py mark <card_id>")
            return 1
        mark_handled(argv[1])
        print(f"Marked handled: {argv[1]}")
        return 0
    if cmd == "clear-history":
        clear_history()
        print("AR XA-handled history cleared.")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
