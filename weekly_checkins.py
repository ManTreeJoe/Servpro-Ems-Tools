"""Weekly check-ins for jobs on the Estimating Board.

Every active card on the Estimating board needs a status note sent at
least once a week — even when the adjuster hasn't asked. Keeps the file
on the adjuster's radar so they don't have to chase.

Outbound message reuses the same canonical text as the 48-hour Estimate
Request ack (`estimate_requests.ACK_TEMPLATE`). The user pastes it into
XactAnalysis on each card; the script handles the Trello @-mention, the
Teams DM to the estimator, and the per-card 7-day cadence tracking.

Public API:
    ESTIMATING_BOARD_NAME              — workspace board name (substring match)
    WEEKLY_INTERVAL_DAYS = 7           — default cadence
    find_due_cards(*, interval_days=7) — list cards 7+ days since last note
    mark_weekly_note_sent(card_id)     — stamp timestamp now
    is_due(card_id, *, interval_days=7) — single-card check

Persistence: `weekly_note_sent: {card_id: iso}` (in persistence.py).
"""
from __future__ import annotations

import datetime as _dt

import persistence as per
import trello_client as tc


# Match against workspace board names case-insensitively. "ESTIMATING"
# catches "ESTIMATING", "Estimating - 2026", "EMS Estimating", etc.
ESTIMATING_BOARD_NAME = "ESTIMATING"

WEEKLY_INTERVAL_DAYS = 7

# Reuse the 48h ack template — same wording, sent proactively per week
# per card. Surfaces via `template()` so a caller doesn't need to
# import estimate_requests directly.
def template() -> str:
    """Canonical weekly-status text to copy into XactAnalysis."""
    try:
        import estimate_requests as er
        return er.ACK_TEMPLATE
    except ImportError:
        # Fallback if estimate_requests isn't on the path for some
        # reason — keeps the weekly flow usable in isolation.
        return ("Your inquiry has been received. "
                "Please allow our estimating team 48 hours to address.")


# ── Internals ──────────────────────────────────────────────────────────

def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


_board_id_cache: str | None = None


def _estimating_board_id() -> str | None:
    """Resolve `ESTIMATING_BOARD_NAME` to a board id once per process.
    Returns None when the workspace doesn't have an Estimating board.
    Matches case-insensitively as a substring so renames don't break."""
    global _board_id_cache
    if _board_id_cache is not None:
        return _board_id_cache or None
    try:
        boards = tc.list_boards() or []
    except Exception:
        return None
    target = ESTIMATING_BOARD_NAME.lower()
    for b in boards:
        name = (b.get("name") or "").lower()
        if target in name:
            _board_id_cache = b.get("id") or ""
            return _board_id_cache or None
    _board_id_cache = ""
    return None


def _days_since(iso_ts: str | None) -> float | None:
    """Return float days since `iso_ts`, or None when unset / unparseable."""
    if not iso_ts:
        return None
    dt = _parse_iso(iso_ts)
    if dt is None:
        return None
    return (_utcnow() - dt).total_seconds() / 86400.0


# ── Public API ─────────────────────────────────────────────────────────

def is_due(card_id: str, *, interval_days: int = WEEKLY_INTERVAL_DAYS
            ) -> bool:
    """True when this card hasn't had a weekly note in `interval_days`
    or has none recorded at all."""
    if not card_id:
        return False
    last = per.get_weekly_note_sent(card_id)
    days = _days_since(last)
    if days is None:
        return True
    return days >= interval_days


def mark_weekly_note_sent(card_id: str) -> None:
    """Stamp `card_id` as just-acked. Idempotent."""
    if not card_id:
        return
    per.set_weekly_note_sent(card_id)


def find_due_cards(*, interval_days: int = WEEKLY_INTERVAL_DAYS,
                    progress_cb=None) -> list[dict]:
    """Walk every list on the Estimating board, enumerate active cards,
    return rows for the ones whose last weekly note is `interval_days`+
    days old (or has none on record).

    Each row dict:
        {"card_id", "card_name", "card_url", "list_id", "list_name",
         "board_id", "days_since": float | None,
         "last_note_iso": str | None}

    Network-walk: one /boards/.../lists call + one /lists/.../cards call
    per list. Call from a background thread.

    Returns [] silently when the Estimating board isn't reachable or
    isn't configured.
    """
    board_id = _estimating_board_id()
    if not board_id:
        return []
    # Lists on the board.
    try:
        lists = tc._call(f"/boards/{board_id}/lists",
                          params={"fields": "id,name"}) or []
    except Exception:
        lists = []
    if not lists:
        return []

    sent_map = per.get_weekly_notes_sent() or {}
    out: list[dict] = []
    total = len(lists)
    for i, lst in enumerate(lists, start=1):
        list_id = lst.get("id") or ""
        list_name = lst.get("name") or ""
        if progress_cb is not None:
            try: progress_cb(i, total, list_name)
            except Exception: pass
        try:
            cards = tc.cards_in_list(list_id) or []
        except Exception:
            cards = []
        for c in cards:
            if c.get("closed"):
                continue
            cid = c.get("id") or ""
            if not cid:
                continue
            last_iso = sent_map.get(cid)
            days = _days_since(last_iso)
            if days is not None and days < interval_days:
                continue
            out.append({
                "card_id":       cid,
                "card_name":     c.get("name", ""),
                "card_url":      c.get("shortUrl", ""),
                "list_id":       list_id,
                "list_name":     list_name,
                "board_id":      board_id,
                "days_since":    days,
                "last_note_iso": last_iso,
            })
    # Newest-stale-first ordering — never-acked cards (days=None) go
    # to the top so they don't get buried under cards aged 30+ days.
    out.sort(key=lambda r: (
        0 if r["days_since"] is None else -r["days_since"]))
    return out


# ── CLI (debug / smoke) ────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python weekly_checkins.py preview [--days=N]")
        print("  python weekly_checkins.py mark <card_id>")
        print("  python weekly_checkins.py clear <card_id>")
        return 1
    cmd = argv[0]
    days = WEEKLY_INTERVAL_DAYS
    for a in argv[1:]:
        if a.startswith("--days="):
            try: days = int(a.split("=", 1)[1])
            except ValueError: pass
    if cmd == "preview":
        rows = find_due_cards(interval_days=days)
        print(f"Due cards (>= {days} days since last note, or never): "
              f"{len(rows)}")
        for r in rows[:30]:
            ds = ("never" if r["days_since"] is None
                  else f"{r['days_since']:.1f}d")
            print(f"  [{r['list_name'][:20]:20s}]  {r['card_name'][:40]:40s}  "
                  f"({ds})")
        return 0
    if cmd == "mark":
        if len(argv) < 2:
            print("mark: missing card_id")
            return 2
        mark_weekly_note_sent(argv[1])
        print(f"marked: {argv[1]}")
        return 0
    if cmd == "clear":
        if len(argv) < 2:
            print("clear: missing card_id")
            return 2
        per.set_weekly_note_sent(argv[1], iso_ts="")
        print(f"cleared: {argv[1]}")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
