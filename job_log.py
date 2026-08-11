"""The dated job-log comment the office posts to a Trello card.

    Monday 5/4/26

    Contents/Demo - Wendy/Priscilla/Vince

One line of activities, one list of who was there. A day with several
activities joins them with "/" rather than posting twice, which is how
the office already writes it.

Tech naming is not a style choice — it encodes who someone is. Roster
LEADS are written as initials (ME, FB, ML); everyone else keeps their
first name (Wendy, Priscilla, Vince). `audit_logic.initials_for_name`
is the roster, returning "" for a non-lead, so `initials_for_name(t) or
t` gives the right form for both without a second list to maintain.

Built here rather than in JS so the preview, the clipboard and the
comment that reaches Trello cannot word the same day differently.
"""
import datetime as _dt

SEP = "/"


def _fmt_date(d):
    """'Monday 5/4/26' — no zero padding, two-digit year.

    %-m/%-d is not portable to Windows and %#m is MSVC-only, so the
    padding comes off by hand.
    """
    return f"{d.strftime('%A')} {d.month}/{d.day}/{d.strftime('%y')}"


def parse_date(value=""):
    """A date from an ISO string, a date, or blank for today. Never
    raises — a bad value means today rather than a broken comment."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    txt = str(value or "").strip()
    if not txt:
        return _dt.date.today()
    try:
        return _dt.date.fromisoformat(txt)
    except ValueError:
        return _dt.date.today()


def tech_label(name):
    """Initials for a roster lead, first name for everyone else."""
    name = str(name or "").strip()
    if not name:
        return ""
    try:
        import audit_logic
        return audit_logic.initials_for_name(name) or name
    except Exception:
        return name


def format_techs(techs):
    """'Wendy/Priscilla/Vince', de-duplicated, order preserved.

    Order is the order they were picked — the office lists the lead
    first when there is one, and re-sorting would fight that.
    """
    out, seen = [], set()
    for t in techs or []:
        label = tech_label(t)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            out.append(label)
    return SEP.join(out)


def format_activities(activities):
    out, seen = [], set()
    for a in activities or []:
        a = str(a or "").strip()
        if a and a.casefold() not in seen:
            seen.add(a.casefold())
            out.append(a)
    return SEP.join(out)


def comment_text(activities, techs, date_value="", monitor_lead=""):
    """The full comment.

    `monitor_lead` adds a second `Monitor - <lead>` line for the case
    where the lead swung by to monitor on a day whose log is something
    else (a Demo day, say). It is ignored when the log IS a monitor —
    the same person would otherwise appear twice on one day.

    Returns {ok, text, ...} or {ok: False, error}.
    """
    acts = format_activities(
        [activities] if isinstance(activities, str) else activities)
    if not acts:
        return {"ok": False, "error": "pick at least one activity"}
    who = format_techs([techs] if isinstance(techs, str) else techs)
    d = parse_date(date_value)

    lines = [_fmt_date(d), "", f"{acts} - {who}" if who else acts]

    lead = tech_label(monitor_lead)
    is_monitor = any(a.casefold() == "monitor" for a in acts.split(SEP))
    if lead and not is_monitor:
        lines += ["", f"Monitor - {lead}"]

    return {"ok": True, "text": "\n".join(lines), "date": d.isoformat(),
            "activities": acts, "techs": who,
            "monitor_lead": lead if (lead and not is_monitor) else ""}
