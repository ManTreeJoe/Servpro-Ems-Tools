"""Workbook specs for the Spreadsheets panel — the Tk-free half.

The specs (Snapshots, Disputes) were defined in `spreadsheet_gui` and
registered as a side effect of importing it. That made `spreadsheet_web`
import a tkinter module purely to populate a registry: the panel renders
an empty list otherwise, because nothing else calls `wbr.register`.

Nothing in a spec needs Tk. Columns, readers, row formatters and tag
colours are all plain data — only the `actions` are Tk (button factories
that open the Disputes panel and refresh it), and the web panel never
uses them. So the specs live here without actions, and spreadsheet_gui
re-registers Disputes with them attached. `wbr.register` overrides by
key and preserves registration order, so the web panel sees the plain
spec and the Tk panel sees the one with buttons.

`theme` is safe to import now — it stopped calling apply_appearance() at
module scope, so it no longer drags customtkinter in for its colours.
"""
from datetime import datetime

import snapshots_excel as sx
import workbook_registry as wbr
from theme import DANGER_BG, SUCCESS_BG, WARN_BG


def _fmt_date_for_row(v):
    """Shared date formatter used by spec row builders so all
    workbooks render dates the same way."""
    if isinstance(v, datetime):
        return v.strftime("%m/%d/%y")
    if isinstance(v, str):
        return v[:10]
    return str(v) if v not in (None, "") else ""

SNAPSHOTS_COLUMNS = (
    wbr.ColumnSpec("sheet",    "Tab",      90),
    wbr.ColumnSpec("name",     "Name",     220),
    wbr.ColumnSpec("received", "Received", 90),
    wbr.ColumnSpec("closing",  "Closing",  90),
    wbr.ColumnSpec("carrier",  "Carrier",  100),
    wbr.ColumnSpec("claim",    "Claim#",   130),
    wbr.ColumnSpec("lead",     "Lead",     90),
    wbr.ColumnSpec("atp",      "ATP",      50),
    wbr.ColumnSpec("cif",      "CIF",      50),
    wbr.ColumnSpec("cer",      "CER",      50),
    wbr.ColumnSpec("cos",      "COS",      50),
)


def _snapshots_row_to_values(r):
    """Convert a Snapshots-workbook row dict to the Treeview tuple
    matching SNAPSHOTS_COLUMNS below."""
    return (
        r.get("_sheet") or "",
        str(r.get("Name") or ""),
        _fmt_date_for_row(r.get("Date Received")),
        _fmt_date_for_row(r.get("Closing Date")),
        r.get("Carrier") or "",
        r.get("Claim#") or "",
        r.get("Lead") or "",
        r.get("ATP") or "",
        r.get("CIF") or "",
        r.get("CER") or "",
        r.get("COS") or "",
    )


SNAPSHOTS_SPEC = wbr.WorkbookSpec(
    key="snapshots",
    label="Snapshots",
    read_rows=sx.read_jobs,
    workbook_path=sx.workbook_path,
    sheets=("All", "NEW LOSS", "Completed", "Incomplete"),
    columns=SNAPSHOTS_COLUMNS,
    row_to_values=_snapshots_row_to_values,
    tag_for_row=lambda r: r.get("_sheet") or None,
    tag_colors={
        "NEW LOSS":   WARN_BG,
        "Completed":  SUCCESS_BG,
        "Incomplete": DANGER_BG,
    },
    pending_count=sx.pending_count,
    actions=(
        wbr.ActionSpec(
            label="↻ Sync backlog → spreadsheet",
            kind="warn",
            command_factory=lambda app: app._sync_backlog,
            attr_name="_backlog_btn",
            tooltip=("Re-audit every job in the year and write the "
                     "results into the workbook (takes a few minutes)")),
        wbr.ActionSpec(
            label="🔄 Reconcile with Trello",
            kind="send",
            command_factory=lambda app: app._reconcile,
            attr_name="_reconcile_btn",
            tooltip=("Walk every row, look up the linked Trello card, "
                     "and re-route to NEW LOSS / Completed / Incomplete "
                     "based on the card's state. Excel must be closed.")),
        wbr.ActionSpec(
            label="🧹 Dedupe rows",
            kind="secondary",
            command_factory=lambda app: app._dedupe,
            attr_name="_dedupe_btn",
            tooltip=("Find rows whose Names match after case-folding, "
                     "whitespace normalization, and comma-swap. "
                     "Preview the plan, then merge into one keeper "
                     "row each. Excel must be closed.")),
        wbr.ActionSpec(
            label="🔍 Cross-check Trello",
            kind="secondary",
            command_factory=lambda app: app._cross_check,
            attr_name="_crosscheck_btn",
            tooltip=("Walk every row, compare its sheet to where the "
                     "pinned Trello card says it belongs, and show only "
                     "the disagreements.")),
        wbr.ActionSpec(
            label="📝 Generate notes",
            kind="secondary",
            command_factory=lambda app: app._generate_notes,
            attr_name="_notes_btn",
            tooltip=("For every row whose Comment cell is blank, pull "
                     "the latest Trello comments + 'needs:' list and "
                     "show you a confirm dialog. You edit + save each "
                     "or skip. Nothing writes without your OK.")),
    ),
)


def _disputes_read_rows(_year):
    """Year arg is ignored — single workbook, not per-year.

    Stamps a synthetic `_sheet` value on each row so the panel's
    sheet-filter dropdown (`All / Open / Overdue / Needs ack /
    Closed`) routes correctly. The Disputes workbook is single-sheet
    in the file itself; the "sheets" tuple here is repurposed as
    aging buckets, and the bucket is derived from the same tag logic
    `_disputes_tag_for_row` uses for color."""
    try:
        import dispute_tracker as _dt
    except Exception:
        return []
    rows = _dt.read_rows()
    for r in rows:
        tag = _disputes_tag_for_row(r)
        if tag == "overdue":
            r["_sheet"] = "Overdue"
        elif tag == "needs_ack":
            r["_sheet"] = "Needs ack"
        elif tag == "closed":
            r["_sheet"] = "Closed"
        else:
            r["_sheet"] = "Open"
    return rows


def _disputes_workbook_path(_year):
    try:
        import dispute_tracker as _dt
        return _dt.path()
    except Exception:
        return ""


def _disputes_row_to_values(r):
    """Convert a Disputes row dict → Treeview tuple matching
    DISPUTES_COLUMNS below. Order kept stable when this code changes."""
    return (
        str(r.get("status") or ""),
        _fmt_date_for_row(r.get("received_date")),
        str(r.get("claim") or ""),
        str(r.get("insured") or ""),
        str(r.get("carrier") or ""),
        str(r.get("intake_source") or ""),
        str(r.get("priority") or ""),
        str(r.get("ack_email_sent") or ""),
        str(r.get("assigned_estimator") or ""),
        _fmt_date_for_row(r.get("assigned_date")),
        _fmt_date_for_row(r.get("target_response_date")),
        _fmt_date_for_row(r.get("next_follow_up_date")),
        str(r.get("outcome") or ""),
    )


def _disputes_tag_for_row(r):
    """Color tag — overdue > needs-ack > new > closed > default."""
    status = (r.get("status") or "").strip().lower()
    if status == "closed":
        return "closed"
    # Overdue?
    tgt = r.get("target_response_date")
    if tgt:
        try:
            import datetime as _dt
            if isinstance(tgt, (_dt.datetime, _dt.date)):
                d = (tgt.date()
                      if isinstance(tgt, _dt.datetime) else tgt)
            else:
                d = _dt.datetime.fromisoformat(str(tgt)[:10]).date()
            if d < _dt.date.today():
                return "overdue"
        except (ValueError, TypeError):
            pass
    if (r.get("ack_email_sent") or "").strip().lower() != "yes":
        return "needs_ack"
    return "open"


DISPUTES_COLUMNS = (
    wbr.ColumnSpec("status",     "Status",        110),
    wbr.ColumnSpec("received",   "Received",      90),
    wbr.ColumnSpec("claim",      "Claim #",       100),
    wbr.ColumnSpec("insured",    "Insured",       200),
    wbr.ColumnSpec("carrier",    "Carrier",       100),
    wbr.ColumnSpec("intake",     "Intake",        70),
    wbr.ColumnSpec("priority",   "Priority",      70),
    wbr.ColumnSpec("ack",        "Ack?",          50),
    wbr.ColumnSpec("estimator",  "Estimator",     90),
    wbr.ColumnSpec("assigned",   "Assigned",      90),
    wbr.ColumnSpec("target",     "Target",        90),
    wbr.ColumnSpec("nextfu",     "Next Follow-Up", 100),
    wbr.ColumnSpec("outcome",    "Outcome",       90),
)


DISPUTES_SPEC = wbr.WorkbookSpec(
    key="disputes",
    label="Disputes",
    read_rows=_disputes_read_rows,
    workbook_path=_disputes_workbook_path,
    # Use logical filters as "sheets". The viewer doesn't actually
    # split by sheet — Disputes is a single-sheet workbook — but the
    # filter dropdown is the right place to expose these aging buckets.
    sheets=("All", "Open", "Overdue", "Needs ack", "Closed"),
    columns=DISPUTES_COLUMNS,
    row_to_values=_disputes_row_to_values,
    tag_for_row=_disputes_tag_for_row,
    tag_colors={
        "overdue":   DANGER_BG,
        "needs_ack": WARN_BG,
        "open":      SUCCESS_BG,
        "closed":    "#EEEEEE",
    },
    pending_count=(lambda _year:
        __import__("dispute_tracker").pending_count()),
)


# Registered here, so importing THIS module is all the web panel needs.
wbr.register(SNAPSHOTS_SPEC)
wbr.register(DISPUTES_SPEC)

