"""Generate per-job comment-cell summaries for the Snapshots spreadsheet.

Pulls the recent activity from the linked Trello card (latest 1-2
comments + current lane + checklist completion) and pairs it with the
spreadsheet's known unfilled fields (ATP/CIF/CER/COS yes/no, missing
dates, etc.) into a compact 2-4 line summary the user can paste into
the Comment cell.

The user reviews + confirms before anything is written — these are
just suggestions. Designed so that an empty card or unmatched client
still produces a usable "needs:" line from the spreadsheet row alone.

Public entry point:
    generate_summary_for_row(row, *, max_chars=600) -> str
"""
from __future__ import annotations

import re as _re
from datetime import datetime as _dt


# Fields on a workbook row that should map to "X needed" callouts when
# the cell is "no" or blank. Ordered for readable output.
_NEED_LABELS = (
    ("ATP",            "ATP"),
    ("CIF",            "CIF"),
    ("CER",            "CER"),
    ("COS",            "COS"),
    ("Initial Photos", "Initial photos"),
    ("Sketch",         "Sketch"),
    ("Demo Photos",    "Demo photos"),
    ("Scope",          "Scope"),
    ("Final Photos",   "Final photos"),
)


def _short(text, n=240):
    """Trim text to ~n chars on a word boundary so multi-paragraph
    Trello comments don't blow out the Comment cell."""
    s = (text or "").strip()
    if not s:
        return ""
    # Collapse runs of whitespace (Trello newlines render fine but make
    # the spreadsheet cell huge).
    s = _re.sub(r"\s+", " ", s)
    if len(s) <= n:
        return s
    cut = s.rfind(" ", 0, n)
    return s[:cut if cut > 0 else n].rstrip() + "…"


def _fmt_date(value):
    """Date cell → 'MM/DD/YY' string. Handles datetime objects and
    pre-stringified workbook values gracefully."""
    if not value:
        return ""
    if isinstance(value, _dt):
        return value.strftime("%m/%d/%y")
    s = str(value).strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%m/%d/%y", "%m/%d/%Y"):
        try:
            return _dt.strptime(s[:19], fmt).strftime("%m/%d/%y")
        except Exception:
            continue
    return s[:10]


def _needs_from_row(row):
    """Yield the "still owed" callouts from the workbook cells alone.
    Independent of Trello so an unmatched job still gets a usable
    summary."""
    out = []
    for col, label in _NEED_LABELS:
        v = (row.get(col) or "").strip().lower()
        if not v or v in ("no", "—", "-", "missing"):
            out.append(label)
    return out


def _recent_trello_lines(card, all_comments=None, *, max_count=2):
    """Render the latest `max_count` human-typed comments from `card`
    as one-liners. Returns a list of strings; empty when no comments
    are available."""
    lines = []
    comments = []
    # Prefer paginated full comments when caller supplied them
    # (snapshot uses `get_all_comments`); fall back to the bundled
    # actions on the card payload.
    if all_comments:
        for c in all_comments:
            if (c.get("type") or "") != "commentCard":
                continue
            comments.append(c)
    elif card:
        for a in (card.get("actions") or []):
            if a.get("type") == "commentCard":
                comments.append(a)
    if not comments:
        return lines
    # Trello returns newest first via the actions feed; preserve it.
    for c in comments[:max_count]:
        text = ((c.get("data") or {}).get("text") or "").strip()
        if not text:
            continue
        author = ((c.get("memberCreator") or {}).get("fullName") or "")
        author = author.split(" ", 1)[0] if author else ""
        when = ""
        iso = (c.get("date") or "").split(".")[0].rstrip("Z")
        if iso:
            try:
                when = _dt.fromisoformat(iso).strftime("%m/%d")
            except Exception:
                pass
        prefix_bits = [b for b in (author, when) if b]
        prefix = (f"{' '.join(prefix_bits)}: " if prefix_bits else "")
        lines.append(prefix + _short(text, 200))
    return lines


def _checklist_status(card):
    """One-line checklist completion summary, or '' when none."""
    if not card:
        return ""
    cls = card.get("checklists") or []
    done = total = 0
    for cl in cls:
        items = cl.get("checkItems") or []
        total += len(items)
        done += sum(1 for it in items
                    if (it.get("state") or "").lower() == "complete")
    if not total:
        return ""
    return f"Checklists: {done}/{total} complete"


def _lane_label(card):
    """Best-effort lane name from the card's list reference. Empty
    when the lookup fails or returns a generic 'Unknown'."""
    if not card:
        return ""
    try:
        import trello_client as tc
        name = tc.get_lane_name(card.get("idBoard"), card.get("idList"))
        if name and name.lower() != "unknown":
            return name
    except Exception:
        pass
    return ""


def generate_summary_for_row(row, *, max_chars=600):
    """Build a compact Comment-cell suggestion for one workbook row.

    Args:
        row:        Dict from `snapshots_excel.read_jobs(year)` — must
                    have at least `Name` and ideally `Claim#`,
                    `Carrier`, ATP/CIF/etc.
        max_chars:  Hard cap on the output length so the Comment cell
                    stays readable.

    Returns:
        Plain-text summary string, never None. Empty string only when
        the row has no usable signals (no name, no needs, no card).

    Composition (newline-separated, lines suppressed when empty):
        1. Status line: `Sheet · Lane · Closed: MM/DD/YY`
        2. Most-recent Trello comment(s) — up to 2, prefixed by author + date
        3. Needs line: `Needs: ATP, CIF, ...` from yes/no cells
        4. Checklist completion: `Checklists: N/M complete`

    Best-effort — every external lookup (Trello fetch, lane name) is
    wrapped in try/except so a Trello outage degrades to a needs-only
    summary instead of an empty string."""
    name = (row.get("Name") or "").strip()
    if not name:
        return ""

    card = None
    all_comments = None
    try:
        import snapshots_excel as sx
        card_id, _err = sx._resolve_card_for_client(name)
    except Exception:
        card_id = None
    if card_id:
        try:
            import trello_client as tc
            card = tc.get_card(card_id)
        except Exception:
            card = None
        if card:
            try:
                import trello_client as tc
                all_comments = tc.get_all_comments(card_id, max_pages=4)
            except Exception:
                all_comments = None

    sheet = (row.get("_sheet") or "").strip()
    lane = _lane_label(card)
    closing = _fmt_date(row.get("Closing Date"))
    status_bits = []
    if sheet:
        status_bits.append(sheet)
    if lane:
        status_bits.append(lane)
    if sheet == "Completed" and closing:
        status_bits.append(f"closed {closing}")
    elif sheet == "Incomplete" and closing:
        status_bits.append(f"closed {closing}")
    status_line = (" · ".join(status_bits)) if status_bits else ""

    recent_lines = _recent_trello_lines(card, all_comments, max_count=2)

    needs = _needs_from_row(row)
    needs_line = ("Needs: " + ", ".join(needs)) if needs else ""

    checklist_line = _checklist_status(card)

    parts = []
    if status_line:
        parts.append(status_line)
    parts.extend(recent_lines)
    if needs_line:
        parts.append(needs_line)
    if checklist_line:
        parts.append(checklist_line)

    out = "\n".join(parts).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rstrip() + "…"
    return out
