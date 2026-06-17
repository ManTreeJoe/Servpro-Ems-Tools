"""Cross-source state reconciler — surface jobs where the Snapshots
spreadsheet's sheet assignment disagrees with what the linked Trello
card suggests.

v1 scope: spreadsheet `_sheet` (NEW LOSS / Completed / Incomplete) vs
`trello_client.card_route_status` (the same three buckets, decided
from Trello board + labels + comments). Job-notes stage and photo-
chip checks are out-of-scope until the user asks — they introduce a
lot of noise on jobs mid-stage where the spreadsheet legitimately
hasn't been updated yet.

Public:
    find_disagreements(year=None, *, progress_cb=None) -> list[dict]
        Each dict: {"name", "sheet", "trello_route", "card_id", "url"}

UI integration: spreadsheet_gui adds a "🔍 Cross-check" button that
runs `find_disagreements` in the background and renders the list in a
small dialog with per-row "Move to {trello_route}" / "Snooze" / "Open
card" actions.
"""
from datetime import datetime


def _is_self_pay(row):
    """Self-pay jobs intentionally route differently — skip them so
    they don't drown the disagreement list. The carrier cell is the
    canonical marker."""
    carrier = (row.get("Carrier") or "").strip().lower()
    return carrier in ("self pay", "selfpay", "self-pay")


def find_disagreements(year=None, *, progress_cb=None,
                        skip_self_pay=True, limit=None):
    """Walk every row in the year's workbook, look up each row's pinned
    Trello card, and yield disagreements where the spreadsheet sheet
    differs from `card_route_status`.

    Args:
        year:           Workbook year (default = today's).
        progress_cb:    Optional `fn(i, total, name)` for status text.
        skip_self_pay:  Self Pay rows are excluded by default — they
                        route by hand-tagged Carrier cell, not by
                        Trello state, and would always disagree.
        limit:          Stop after N rows (debugging only — default
                        None walks the whole workbook).

    Returns a list of disagreement dicts:
        {
          "name":          str  – Name cell as written in workbook
          "sheet":         str  – current sheet ("NEW LOSS" etc.)
          "trello_route":  str  – Trello suggestion ("completed"/...)
          "card_id":       str  – pinned card id
          "url":           str  – shortcut to card
          "claim":         str  – workbook Claim# (for context)
          "carrier":       str  – workbook Carrier (for context)
        }
    Returns an empty list when the workbook can't be opened or there
    are no rows to scan.
    """
    try:
        import snapshots_excel as sx
        import trello_client as tc
    except Exception:
        return []

    yr = year or datetime.today().year
    rows = []
    try:
        rows = sx.read_jobs(yr) or []
    except Exception:
        rows = []

    if not rows:
        return []

    if limit is not None:
        rows = rows[:limit]

    out = []
    total = len(rows)
    for i, r in enumerate(rows, 1):
        name = (r.get("Name") or "").strip()
        if not name:
            continue
        if skip_self_pay and _is_self_pay(r):
            continue
        if progress_cb:
            try:
                progress_cb(i, total, name)
            except Exception:
                pass

        # Resolve the pinned card. `_resolve_card_for_client` returns
        # (card_id, error_str); we only care about hits with an id.
        try:
            card_id, _err = sx._resolve_card_for_client(name)
        except Exception:
            card_id = None
        if not card_id:
            continue

        try:
            card = tc.get_card(card_id, actions_limit=50)
        except Exception:
            card = None
        if not card:
            continue

        try:
            trello_route = tc.card_route_status(card)
        except Exception:
            continue

        spreadsheet_sheet = (r.get("_sheet") or "").strip()
        if _route_matches_sheet(trello_route, spreadsheet_sheet):
            continue

        out.append({
            "name":         name,
            "sheet":        spreadsheet_sheet,
            "trello_route": trello_route,
            "card_id":      card_id,
            "url":          (card.get("shortUrl")
                              or card.get("url") or ""),
            "claim":        (r.get("Claim#") or "").strip(),
            "carrier":      (r.get("Carrier") or "").strip(),
        })

    return out


_ROUTE_TO_SHEET = {
    "completed":  "Completed",
    "incomplete": "Incomplete",
    "new_loss":   "NEW LOSS",
}


def _route_matches_sheet(trello_route, sheet_title):
    """True when the Trello-suggested route and the spreadsheet sheet
    name represent the same bucket."""
    expected = _ROUTE_TO_SHEET.get((trello_route or "").lower())
    if not expected:
        return True  # Unknown route → treat as agreement (no signal).
    return (sheet_title or "").strip() == expected


def route_to_sheet(trello_route):
    """Public helper for UI callers — convert a route string to its
    spreadsheet sheet name."""
    return _ROUTE_TO_SHEET.get((trello_route or "").lower())
