"""The Initial Inspection email/note sent to the adjuster.

The office writes this by hand for every new job, off the tech's initial
inspection notes. Nearly every line of it is already sitting in those
notes — `initial_notes_parser` pulls Date, Time, Met With, COL, CAT,
levels, room lists, testing, packout, equipment and the video link — so
this composes the draft and leaves the operator to fill the gaps.

The WORDING is the user's, verbatim. These are sentences an adjuster
reads on every claim, so they are fixed strings driven by yes/no answers
rather than anything generated: an adjuster who sees "Re-inspection is
recommended upon completion of repairs" on twenty claims should see the
same sentence on the twenty-first.

Anything the notes don't answer becomes a `[BRACKETED]` placeholder
rather than being guessed or silently dropped — a wrong arrival time on
a claim document is worse than a blank one, and a bracket is visible in
the dialog before it is copied.
"""
import datetime as _dt
import re

PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9 /&'-]{2,40}\]")

# Yes/No answers arrive as "Yes", "No", "Yes /", "/ No", "" (unanswered).
_YES = ("yes", "y", "true", "required", "needed")
_NO = ("no", "n", "false", "not required", "none")


def _tri(value):
    """True / False / None (unanswered) from a tech's yes-no answer.

    The template prints "Yes / No" and the tech strikes one out, so the
    answer arrives as "Yes /", "/ No", or — when they skipped it — the
    untouched "Yes / No". BOTH options still present means UNANSWERED,
    and that has to be checked first: a prefix test alone reads
    "Yes / No" as Yes, which would assert "Asbestos and Lead testing is
    required" on a claim the tech never answered.
    """
    v = (str(value or "")).strip().strip("/").strip().lower()
    if not v:
        return None
    words = re.split(r"[^a-z]+", v)
    if any(w == "yes" for w in words) and any(w == "no" for w in words):
        return None                      # untouched — nobody answered
    for token in _YES:
        if v == token or v.startswith(token + " "):
            return True
    for token in _NO:
        if v == token or v.startswith(token + " "):
            return False
    return None


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def format_inspection_date(raw, comma=False):
    """'6/29/26' -> 'Monday 6/29/26'. The weekday is what the office
    writes, and deriving it beats asking someone to look at a calendar.
    Unparseable input is returned untouched — never invent a date.

    `comma` gives 'Tuesday, 6/30/26'. The office punctuates the crews-en-
    route line that way and the inspection line without; matching what
    they already send is the whole point of a fixed template.
    """
    txt = _clean(raw)
    if not txt:
        return ""
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", txt)
    if not m:
        return txt
    mo, day, yr = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if yr < 100:
        yr += 2000
    try:
        d = _dt.date(yr, mo, day)
    except ValueError:
        return txt
    # Already carries a weekday? Don't double it up.
    if re.search(r"(mon|tues|wednes|thurs|fri|satur|sun)day", txt, re.I):
        return txt
    sep = ", " if comma else " "
    return f"{d.strftime('%A')}{sep}{m.group(0)}"


def _rooms_block(fields):
    """The affected-areas section, per level.

    Techs fill Upstairs / Downstairs with room lists; the email prints
    each level as a heading followed by its rooms one per line. A level
    with nothing recorded is skipped rather than printed empty.
    """
    out = []
    levels = _clean(fields.get("Levels Affected"))
    out.append("Areas affected:")
    out.append(f"Number of Levels Affected: {levels or '[LEVELS]'}")
    out.append("")
    any_rooms = False
    for label in ("Downstairs", "Upstairs"):
        raw = _clean(fields.get(label))
        if not raw:
            continue
        any_rooms = True
        out.append(f"{label}:")
        out.append("")
        # Rooms are written comma- or newline-separated; one per line
        # reads the way the office sends it.
        for room in [r.strip() for r in re.split(r"[;\n]|,(?![^(]*\))", raw)
                     if r.strip()]:
            out.append(room)
            out.append("")
    if not any_rooms:
        out.append("[AFFECTED AREAS]")
        out.append("")
    return out


def compose(fields, *, franchise="", supervisor="", greeting="Good Morning,",
            year_built="", equipment_rate="", crews_date="",
            walkthrough_url="", docusketch_url="", extras=None):
    """Render the email. `fields` is one block from
    `initial_notes_parser.parse_initial_inspection_notes`.

    `extras` overrides any auto-derived yes/no so the operator can assert
    something the notes left blank (the dialog's checkboxes).
    """
    f = dict(fields or {})
    ex = dict(extras or {})

    def flag(key, note_key):
        if key in ex:
            return bool(ex[key])
        return _tri(f.get(note_key))

    L = []
    # No franchise line. It goes out from a mailbox that already
    # identifies the office, so naming the franchise on top only
    # restated it — and on any job where it wasn't configured a literal
    # "[FRANCHISE]" went out to an adjuster. `franchise` is still
    # accepted so callers don't all have to change.
    L.append(greeting or "Good Morning,")
    L.append("")

    date_txt = format_inspection_date(f.get("Date"))
    sup = _clean(supervisor) or "[SUPERVISOR]"
    L.append(f"Initial Inspection performed {date_txt or '[DATE]'} "
             f"Supervisor {sup}")
    L.append("")
    L.append(f"Arrival Time: {_clean(f.get('Time')) or '[ARRIVAL TIME]'}")
    L.append(f"Met With: {_clean(f.get('Met With')) or '[MET WITH]'}")
    L.append("")
    L.append(f"COL: {_clean(f.get('Cause of Loss')) or '[CAUSE OF LOSS]'}")
    L.append("")
    L.append(f"CAT: {_clean(f.get('Category')) or '[CAT]'}")
    L.append("")

    repairs = flag("repairs_done", "Plumbing Repairs")
    if repairs is True:
        L.append("Repairs have been completed")
    else:
        L.append("Repairs have yet to be completed")
    L.append("")

    # Leak detection sits between Repairs and Re-inspection in the
    # official note. The notes parser has captured "Leak Detection" all
    # along; the email simply never printed it, so the office retyped it.
    if flag("leak_detection", "Leak Detection") is True:
        L.append("Leak detection is recommended")
        L.append("")

    if flag("reinspection", "Re-inspection") is not False:
        L.append("Re-inspection is recommended upon completion of repairs")
        L.append("")

    # Also parsed and never printed. A reading only means something with
    # its value attached, so it prints only when the tech recorded one —
    # no bracket, since a bare "Water Heater Temp Set -" tells an adjuster
    # nothing the omission doesn't.
    water_heater = _clean(f.get("Water Heater Temp"))
    if water_heater:
        L.append(f"Water Heater Temp Set - {water_heater}")
        L.append("")

    L.extend(_rooms_block(f))

    if _clean(year_built):
        L.append(f"Property built in {_clean(year_built)}")
        L.append("")

    if flag("testing", "Asbestos/Lead Test") is True:
        L.append("Asbestos and Lead testing is required")
        L.append("")

    # Mold. "Visible Mold" / "Mold Sq Ft" have always been parsed and
    # never printed, so every mold job had this block retyped by hand.
    if flag("mold", "Visible Mold") is True:
        sq = _clean(f.get("Mold Sq Ft")).lower()
        under_ten = ("less" in sq) or ("<" in sq) or ("under" in sq)
        over_ten = ("greater" in sq) or ("more" in sq) or (">" in sq) \
            or ("over" in sq)
        if under_ten:
            L.append("Microbial growth less than 10sqft present")
        elif over_ten:
            L.append("Microbial growth greater than 10sqft present")
        else:
            L.append("Microbial growth present")
        L.append("")
        # Only the UNDER-ten wording exists in the office's sent emails.
        # Above ten the opposite holds — remediation IS warranted — so
        # those follow-on sentences are deliberately not guessed. The
        # operator adds them in the draft box, which is the same place
        # this whole block used to be typed.
        if under_ten:
            L.append("Remediation not warranted")
            L.append("")
            L.append("Servpro to address")
            L.append("")
            L.append("An air scrubber will be utilized throughout the "
                     "duration of the remediation")
            L.append("")
            L.append("Please advise on approvals")
            L.append("")

    if flag("packout", "Packout Required") is True:
        L.append("Pack out will be necessary to facilitate mitigation")
        L.append("")
        L.append("Packing materials will be utilized")
        L.append("")
        L.append("The time allotted per room under the SLA will be exceeded")
        L.append("")
        storage = _clean(f.get("Storage Type")).lower()
        if ex.get("pod") if "pod" in ex else ("pod" in storage):
            L.append("POD is required")
            L.append("")
        if ex.get("tl_inventory", True):
            L.append("TL inventory is required")
            L.append("")

    if flag("equipment", "Equipment Placed") is not False:
        L.append("Equipment placed to stabilize environment")
        L.append("")
        if ex.get("dry_time_exceeded", True):
            L.append("Three-day dry time will be exceeded")
            L.append("")
        rate = _clean(equipment_rate)
        L.append("Please note, equipment onsite is incurring costs at "
                 f"{rate or '[$/DAY]'} per day")
        L.append("")

    services = [s for s in (ex.get("services") or []) if _clean(s)]
    if services:
        L.append("Please be advised, on this claim the following services "
                 "are going to be performed due:")
        L.append("")
        for s in services:
            L.append(_clean(s))
            L.append("")

    if ex.get("esl_exceeded", True):
        L.append("Please note, ESL will be exceeded")
        L.append("")

    if _clean(crews_date):
        L.append("Crews en route to commence mitigation "
                 f"{format_inspection_date(crews_date, comma=True)}")
        L.append("")

    url = _clean(walkthrough_url) or _clean(f.get("Video Taken"))
    if url.lower().startswith("http"):
        L.append("Please copy & paste the link below into your preferred "
                 "browser to view initial walkthrough:")
        L.append(url)
        L.append("")

    # DocuSketch. Same shape as the walkthrough link above — the office
    # was pasting this whole section in by hand on every job that has a
    # sketch, because the email had no place for it at all.
    sketch = _clean(docusketch_url) or _clean(f.get("DocuSketch Done"))
    if sketch.lower().startswith("http"):
        L.append("Please copy & paste the link below into your preferred "
                 "browser to view the DocuSketch:")
        L.append(sketch)
        L.append("")

    L.append("Regards,")

    # Collapse any run of >1 blank line the conditionals left behind.
    out, blank = [], False
    for line in L:
        if line == "":
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def missing_placeholders(text):
    """The [BRACKETS] still in a draft — shown in the dialog so nothing
    goes to an adjuster with a hole in it."""
    return sorted(set(PLACEHOLDER_RE.findall(text or "")))
