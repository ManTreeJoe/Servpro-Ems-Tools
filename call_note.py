"""Timestamped contact notes for a Trello card.

The office already writes these by hand, in this shape:

    11:05 8/12/2026
    Called Insured to collect email.
    LVM

A time-and-date line, then what happened. That is all it is — the value
is that it is *consistent* and *timestamped*, so a card's comment history
reads as a call log instead of a pile of undated remarks.

The text is built HERE, never in the browser, so the preview the user
approves and the string that reaches Trello are the same object. A second
formatter in JS is exactly how the job-log and activity comments drifted
into writing the same day two different ways.
"""

import datetime as _dt
import re


# Shorthand the office already uses. Offered as one-click chips so the
# note stays consistent — "LVM" beats five spellings of "left a voicemail".
QUICK_PHRASES = [
    "LVM",                      # left voicemail
    "No answer",
    "Line busy",
    "Wrong number",
    "Left message with office",
    "Spoke with insured",
    "Spoke with adjuster",
    "Call back requested",
    "Emailed instead",
]


def stamp(when=None):
    """The header line: `H:MM M/D/YYYY` — e.g. `11:05 8/12/2026`.

    Not zero-padded on the hour or the month ("11:05 8/12/2026", not
    "11:05 08/12/2026"), because the existing comments on these cards are
    written that way and a log that changes format halfway through is
    harder to scan, not easier.

    The clock is 24-HOUR. The sample this was built from ("11:05") is the
    same either way, but a 12-hour clock without am/pm cannot tell 2:30
    in the afternoon from 2:30 at night — and these notes are evidence of
    when someone was contacted, so losing that is worse than looking
    slightly technical. Input still accepts "2:30 pm"; only the stored
    form is unambiguous.
    """
    d = when or _dt.datetime.now()
    return f"{d.hour}:{d.minute:02d} {d.month}/{d.day}/{d.year}"


def _parse_time(text):
    """`HH:MM` (24h) or `H:MM am/pm` → (hour, minute), or None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", t)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    ap = m.group(3)
    if mm > 59:
        return None
    if ap:
        if not 1 <= hh <= 12:
            return None
        hh = (hh % 12) + (12 if ap == "pm" else 0)
    elif hh > 23:
        return None
    return hh, mm


def build(body, *, time_text="", date_iso=""):
    """Compose the comment. Returns {ok, text, error}.

    `time_text` / `date_iso` override "now" so a call can be logged after
    the fact — you rarely stop mid-call to write it down. Both are
    optional and each falls back to now independently.

    The body is passed through as typed apart from trimming: it is the
    part a human wrote and second-guessing it would only surprise them.
    """
    body = (body or "").strip()
    if not body:
        return {"ok": False, "error": "nothing to log"}

    now = _dt.datetime.now()
    day = now.date()
    if date_iso:
        try:
            day = _dt.date.fromisoformat(str(date_iso).strip())
        except ValueError:
            return {"ok": False, "error": f"bad date: {date_iso!r}"}

    hh, mm = now.hour, now.minute
    if time_text:
        parsed = _parse_time(time_text)
        if not parsed:
            return {"ok": False, "error": f"bad time: {time_text!r}"}
        hh, mm = parsed

    when = _dt.datetime(day.year, day.month, day.day, hh, mm)
    # Collapse runs of blank lines inside the body — a stray double
    # return shouldn't put a gap in the middle of a two-line note.
    lines = [ln.rstrip() for ln in body.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln.strip():
            blank = True
            continue
        if blank and out:
            out.append("")
        blank = False
        out.append(ln)
    return {"ok": True, "text": stamp(when) + "\n" + "\n".join(out)}
