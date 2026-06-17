"""End-of-day digest — automatic daily log for handoff coverage.

Walks the existing state on disk (persistence.json, the Snapshots
workbook, hygiene snooze records) and produces a Markdown file
summarizing what happened on a given date. No new event-logging
plumbing is needed for v1: every signal it surfaces is already
recorded somewhere as a side-effect of normal tool use.

Generated files live at:
    X:\\IE_Public\\Daily Digest\\YYYY-MM-DD.md

Public entry points:
    build_digest(date=None) → str  (markdown text, no file write)
    write_digest(date=None) → path str  (writes + returns path)
    open_today_digest()       (writes today's + os.startfile's it)
"""
import os
from datetime import datetime

DIGEST_ROOT_DEFAULT = r"X:\IE_Public\Daily Digest"
_root = DIGEST_ROOT_DEFAULT


def set_root(path):
    global _root
    _root = (path or DIGEST_ROOT_DEFAULT)


def get_root():
    return _root


def digest_path(date):
    """Resolve where today's digest .md lives. Builds the parent dir
    lazily — first call of the day creates X:\\IE_Public\\Daily Digest."""
    d = date or datetime.today()
    fn = f"{d.strftime('%Y-%m-%d')}.md"
    try:
        if not os.path.isdir(_root):
            os.makedirs(_root, exist_ok=True)
    except OSError:
        pass
    return os.path.join(_root, fn)


def _fmt_date(d):
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str):
        s = d.strip()
        if not s:
            return ""
        for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y",
                    "%m-%d-%Y"):
            try:
                return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return s[:10]
    return ""


def _persistence_audit_resolutions_for(date_str):
    """Count audit-issue resolutions keyed to `date_str` (MM-DD-YYYY).
    Returns (count, [(client, issue), ...])."""
    try:
        import persistence
    except Exception:
        return (0, [])
    try:
        resolved = persistence._load().get("resolved_issues", {})
    except Exception:
        return (0, [])
    out = []
    prefix = f"{date_str}::"
    for key, val in resolved.items():
        if not val:
            continue
        if not key.startswith(prefix):
            continue
        tail = key[len(prefix):]
        if "::" not in tail:
            continue
        client, issue = tail.split("::", 1)
        out.append((client, issue))
    return (len(out), out)


def _persistence_audit_comments_for(date_str):
    """Count Trello comments posted from audit rows on `date_str`."""
    try:
        import persistence
    except Exception:
        return (0, [])
    try:
        rec = persistence._load().get("audit_comments", {})
    except Exception:
        return (0, [])
    out = []
    for key, posted_date in rec.items():
        if posted_date != date_str:
            continue
        if "::" not in key:
            continue
        client, issue = key.split("::", 1)
        out.append((client, issue))
    return (len(out), out)


def _snapshots_excel_activity_for(date):
    """Return spreadsheet-derived activity for the given datetime.date:
        intake_count, intake_names, closed_count, closed_names
    Intake = rows whose Date Received parses to `date`.
    Closed  = rows on Completed/Incomplete whose Closing Date parses
              to `date`."""
    try:
        import snapshots_excel as sx
    except Exception:
        return (0, [], 0, [])
    yr = date.year if hasattr(date, "year") else datetime.today().year
    try:
        rows = sx.read_jobs(yr)
    except Exception:
        rows = []
    target = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else date
    intake_names, closed_names = [], []
    for r in rows:
        if _fmt_date(r.get("Date Received")) == target:
            intake_names.append((r.get("Name") or "").strip())
        if (r.get("_sheet") in ("Completed", "Incomplete")
                and _fmt_date(r.get("Closing Date")) == target):
            closed_names.append((r.get("Name") or "").strip(),)
    # Flatten the single-tuple noise from the iteration above.
    closed_names = [n[0] if isinstance(n, tuple) else n
                    for n in closed_names]
    # Sweep one-letter / two-letter / clearly-non-name cells the
    # workbook sometimes accumulates from stray typing.
    def _looks_like_name(s):
        s = (s or "").strip()
        return len(s) >= 3 and any(ch.isalpha() for ch in s)
    intake_names = [n for n in intake_names if _looks_like_name(n)]
    closed_names = [n for n in closed_names if _looks_like_name(n)]
    return (len(intake_names), intake_names,
            len(closed_names), closed_names)


def _hygiene_acks_for(date_str):
    """Estimate-request acks (and any other timestamped Hygiene actions
    persistence tracks) that fired on `date_str`. Best-effort — returns
    (count, descriptions)."""
    try:
        import persistence
    except Exception:
        return (0, [])
    try:
        data = persistence._load()
    except Exception:
        return (0, [])
    out = []
    # estimate_request_acks: {req_key: {"acked_on": "MM-DD-YYYY", ...}}
    er = data.get("estimate_request_acks", {}) or {}
    for k, rec in er.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("acked_on") == date_str:
            out.append(f"Estimate ack — {k}")
    return (len(out), out)


def build_digest(date=None):
    """Render today's (or any specified date's) digest as Markdown text.
    Pulls from existing persistence + Snapshots Excel state — no new
    event logging required.

    Output sections:
      • Header (date, weekday)
      • Intake (Snapshots Excel rows whose Date Received == today)
      • Closeouts (Snapshots Excel rows whose Closing Date == today)
      • Audit findings resolved (persistence resolved_issues keyed today)
      • Trello comments posted (persistence audit_comments keyed today)
      • Hygiene actions (estimate-request acks etc.)
    Each section is suppressed when empty so the output stays terse on
    quiet days.
    """
    d = date or datetime.today()
    ymd = d.strftime("%Y-%m-%d")
    mdy = d.strftime("%m-%d-%Y")
    weekday = d.strftime("%A")
    pretty_date = d.strftime("%B %-d, %Y") if os.name != "nt" \
                  else d.strftime("%B ") + str(d.day) + d.strftime(", %Y")

    intake_n, intake_names, closed_n, closed_names = \
        _snapshots_excel_activity_for(d)
    resolved_n, resolved_pairs = _persistence_audit_resolutions_for(mdy)
    comments_n, comments_pairs = _persistence_audit_comments_for(mdy)
    hyg_n, hyg_items = _hygiene_acks_for(mdy)

    lines = []
    lines.append(f"# Daily digest — {pretty_date} ({weekday})")
    lines.append("")
    lines.append(f"_Generated {datetime.today().strftime('%I:%M %p').lstrip('0')}_")
    lines.append("")

    total_signals = intake_n + closed_n + resolved_n + comments_n + hyg_n
    if total_signals == 0:
        lines.append("No tracked activity for this date.")
        lines.append("")
        lines.append("_(This date might predate persistence tracking, or "
                     "no automation tool actions were recorded.)_")
        return "\n".join(lines)

    if intake_n:
        lines.append(f"## Intake — {intake_n} new")
        for n in sorted(intake_names):
            lines.append(f"- {n}")
        lines.append("")

    if closed_n:
        lines.append(f"## Closeouts — {closed_n}")
        for n in sorted(closed_names):
            lines.append(f"- {n}")
        lines.append("")

    if resolved_n:
        lines.append(f"## Audit findings resolved — {resolved_n}")
        # Group by client so a busy job doesn't dominate the list.
        by_client = {}
        for client, issue in resolved_pairs:
            by_client.setdefault(client, []).append(issue)
        for client in sorted(by_client):
            items = by_client[client]
            if len(items) == 1:
                lines.append(f"- **{client}** — {items[0]}")
            else:
                lines.append(f"- **{client}** — {len(items)} items: "
                             f"{', '.join(sorted(items))}")
        lines.append("")

    if comments_n:
        lines.append(f"## Trello comments posted — {comments_n}")
        by_client = {}
        for client, issue in comments_pairs:
            by_client.setdefault(client, []).append(issue)
        for client in sorted(by_client):
            items = by_client[client]
            lines.append(f"- **{client}** — {', '.join(sorted(items))}")
        lines.append("")

    if hyg_n:
        lines.append(f"## Hygiene actions — {hyg_n}")
        for item in sorted(hyg_items):
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_digest(date=None):
    """Render + write the digest to its dated path. Returns the path.
    Overwrites any existing file for the same date (digest is derived
    from state — re-running mid-day is the same idempotent operation)."""
    d = date or datetime.today()
    path = digest_path(d)
    body = build_digest(d)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        return None
    return path


def open_today_digest():
    """Write + open today's digest in the default Markdown viewer.
    Returns the path written, or None if the write failed."""
    path = write_digest(datetime.today())
    if not path:
        return None
    try:
        os.startfile(path)
    except OSError:
        pass
    return path
