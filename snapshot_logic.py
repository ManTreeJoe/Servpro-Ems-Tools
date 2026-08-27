"""Snapshot parsing + PDF-generation logic (UI-free).

Extracted from snapshot_gui.py so the web panels (snapshot_web, audit_web)
and scope_dialog can parse Trello comments / scope blocks and build/fill the
snapshot PDF without importing the 5K-line Tk SnapshotApp. snapshot_gui
re-exports every name here via a shim, so the Tk UI and other callers are
unaffected. See EMS_Tk_Extraction_Plan.md.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

import pdfrw
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle)

import audit_logic
import config

# Fillable snapshot template path — fill_pdf reads it. Resolved lazily
# from config each call so a Settings change or department (OC/IE) switch
# is picked up without a restart. `snapshot_logic.TEMPLATE` still works via
# the module __getattr__ below.
def _template():
    return config.load().get("snapshot_template", "")


def __getattr__(name):
    if name == "TEMPLATE":
        return _template()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_weekday(date_str):
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%A")
        except ValueError:
            pass
    return ""

def fmt_techs(names, initials_only=False):
    # List EVERY tech on the day. The old "first +N" collapse was a crutch for
    # the narrow fillable-template cell; the rendered handoff wraps the techs
    # cell, so all names fit. De-dupe (order-preserving) so a line that repeats
    # a tech doesn't double them.
    seen, out = set(), []
    for n in (nm.strip() for nm in names):
        if not n:
            continue
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return ", ".join(out)

def detect_first_visit(raw):
    """Find the earliest Initial Inspection date from dispatch lines only."""
    date_pattern = re.compile(r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b')
    inspect_pattern = re.compile(r'initial\s+inspection', re.IGNORECASE)
    email_skip = re.compile(
        r'^(from:|to:|subject:|sent:|regards|good morning|good afternoon|'
        r'sincerely|email sent|please|hi |hello|we will|called|left voicemail|'
        r'spoke with|following up|\d{3}-\d{3})', re.IGNORECASE)
    disqualify2 = re.compile(
        r'to schedule|to confirm|regarding the|schedule for|voicemail|'
        r'left message|obtain an update|possibly|tentatively|attorney',
        re.IGNORECASE)
    earliest = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or len(line) > 100 or email_skip.match(line) or disqualify2.search(line):
            continue
        if inspect_pattern.search(line):
            m = date_pattern.search(line)
            if m:
                for fmt in ("%m/%d/%y", "%m/%d/%Y"):
                    try:
                        d = datetime.strptime(m.group(1), fmt)
                        if earliest is None or d < earliest:
                            earliest = d
                        break
                    except ValueError:
                        pass
    if earliest:
        return f"{earliest.month}/{earliest.day}/{str(earliest.year)[2:]}"
    return ""

_CAUSE_RE   = re.compile(r'\b(water|mold|fire|smoke)\b', re.IGNORECASE)
_CAT_RE     = re.compile(r'\bCat(?:egory)?\.?\s*([1-4])\b', re.IGNORECASE)
_CLASS_RE   = re.compile(r'\bClass\s+([1-4])\b', re.IGNORECASE)


def apply_snapshot_field_rules(*, job_title, customer_name, carrier, claim,
                               cause, scan_text):
    """Auto-fill snapshot intake fields based on title + scanned notes.

    Rules for Carrier / Claim # field (priority order):
      1. carrier + claim       → "carrier / claim"
      2. only carrier OR claim → that one
      3. neither (selfpay marker OR commercial — both render the same way)
         → "Self Pay". A commercial job is identified by having both a
         business title AND a customer name that differ; in that case
         customer_name comes back as `customer_for_header` so the PDF
         "Insured / Job" line can render "<title> — <customer>" while
         folder/filename/pin lookups still use the simple title.

    Cause auto-detect (only when cause is blank): scans title+text for
    water/mold/fire/smoke and appends "Cat N" / "Class N" if found.

    Returns (insured_lookup, carrier_line, cause, customer_for_header).
    `customer_for_header` is "" except in the commercial-with-customer
    case. Callers should join it onto the PDF header with " — " when
    truthy, but keep using `insured_lookup` for folder/filename/pin keys.
    """
    title = (job_title or "").strip()
    custom = (customer_name or "").strip()

    customer_for_header = ""

    if carrier and claim:
        carrier_line = f"{carrier} / {claim}"
        insured = custom or title
    elif carrier or claim:
        carrier_line = carrier or claim
        insured = custom or title
    else:
        # No carrier + no claim → self pay or commercial; both render
        # the carrier line the same way. Commercial is detected by the
        # presence of a separate business title vs customer name.
        carrier_line = "Self Pay"
        if (title and custom
                and title.lower() != custom.lower()
                and custom.lower() not in title.lower()):
            insured = title
            customer_for_header = custom
        else:
            insured = title or custom

    if not (cause or "").strip():
        blob = f"{title}\n{custom}\n{scan_text or ''}"
        # Detect EVERY loss type mentioned, not just the first one.
        # Multi-cause jobs (Keystone-style mold + water) read as
        # "Water, Mold" — same canonical order and separator as the
        # Trello-label path in `trello_client.card_loss_type` so the
        # spreadsheet's Type of Loss column and the snapshot's Cause
        # field stay in sync. Order is fixed (Water → Mold → Fire →
        # Smoke) so the output is stable across re-pulls.
        lower_blob = blob.lower()
        causes = [c for c in ("Water", "Mold", "Fire", "Smoke")
                   if re.search(rf"\b{c.lower()}\b", lower_blob)]
        cause_part = ", ".join(causes)
        parts = [cause_part] if cause_part else []
        cm = _CAT_RE.search(blob)
        if cm:
            parts.append(f"Cat {cm.group(1)}")
        cls = _CLASS_RE.search(blob)
        if cls:
            parts.append(f"Class {cls.group(1)}")
        if parts:
            cause = " ".join(parts)

    return insured, carrier_line, cause, customer_for_header


_WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
_WEEKDAY_RE    = re.compile(
    r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b', re.IGNORECASE)

def _align_date_to_weekday(date_str, line):
    """
    If the line names a weekday that doesn't match date_str's actual weekday,
    walk ±1–2 days to find the date that matches the stated day.
    Corrects errors like 'Saturday 4/10' when 4/10 is actually Friday.
    """
    m = _WEEKDAY_RE.search(line)
    if not m:
        return date_str
    target_wd = next((i for i, n in enumerate(_WEEKDAY_NAMES)
                      if n.lower() == m.group(1).lower()), None)
    if target_wd is None:
        return date_str
    dt = None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except Exception:
            pass
    if not dt or dt.weekday() == target_wd:
        return date_str
    from datetime import timedelta as _td
    for delta in (1, -1, 2, -2):
        candidate = dt + _td(days=delta)
        if candidate.weekday() == target_wd:
            return f"{candidate.month}/{candidate.day}/{str(candidate.year)[2:]}"
    return date_str


# ── Email-block sub-contractor extractor ────────────────────────────────────
# Forwarded sub-contractor emails (Safeguard, ADT, etc.) often have a layout
# the line-by-line parser misses entirely:
#   - "From: ... Safeguard EnviroGroup ..." — sub identity, but matches
#     email_skip and gets dropped.
#   - "Subject: Re[2]: ... Mold Clearence" — activity hint, also dropped.
#   - "We have confirmed testing for 4/29..." — has the date, but starts
#     with "We have" so it ALSO matches email_skip.
# Net result: every line that carries any of the signals gets stripped, the
# main loop sees nothing, and Safeguard never appears in the snapshot.
#
# This helper takes the raw text, splits it into email blocks (delimited by
# `From:` lines), and pulls (date, weekday, activity, sub) out of each block
# as a unit. Long-form dates ("April 29, 2026") in `Sent:` headers are
# accepted as a fallback so emails whose body has no slash date still resolve.

_LONG_DATE_RE = re.compile(
    r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|'
    r'may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|'
    r'oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+'
    r'(\d{1,2}),?\s+(\d{4})\b',
    re.IGNORECASE)

_MONTH_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_FROM_LINE_RE = re.compile(r'^\s*From\s*:', re.IGNORECASE)
_HEADER_LINE_RE = re.compile(
    r'^\s*(from|to|subject|sent|cc)\s*:', re.IGNORECASE)
_PARTIAL_SLASH_RE = re.compile(r'\b(\d{1,2})/(\d{1,2})\b(?!/)')


def _split_email_blocks(raw):
    """Split `raw` on `From:` lines so each email becomes one block.
    Anything before the first `From:` becomes its own block (typically
    free-form Trello dispatch lines)."""
    if not raw:
        return []
    blocks = []
    current = []
    for line in raw.splitlines():
        if _FROM_LINE_RE.match(line) and current:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _extract_email_block_subs(raw, sub_keywords, sub_activity_map,
                                sub_billing_default, date_pattern):
    """Pull (date, weekday, activity, sub) tuples out of email blocks
    where the line-by-line parser couldn't see the sub-contractor.

    Only fires for blocks that look like emails (have a `From:` line) and
    name a known sub. Long-form dates from `Sent:` headers are a fallback
    when no slash-format date is in the body."""
    blocks = _split_email_blocks(raw)
    if not blocks:
        return []
    out = []
    seen = set()
    for block in blocks:
        block_text = "\n".join(block)
        block_lower = block_text.lower()
        # Skip non-email blocks (the dispatch-line section before the
        # first email) — the main loop already handles those.
        if not _FROM_LINE_RE.search(block_text):
            continue

        matched_sub = None
        for kw, sub_name in sub_keywords.items():
            if kw in block_lower:
                matched_sub = sub_name
                break
        if not matched_sub:
            continue

        activity = None
        for pattern, label in sub_activity_map:
            if re.search(pattern, block_lower):
                activity = label
                break
        # Order-agnostic check: "PASSED ... clearance criteria" reverses
        # the `clearance.*pass` pattern, so accept it explicitly.
        if not activity and ("passed" in block_lower
                             and ("clear" in block_lower
                                  or "criteria" in block_lower)):
            activity = "Mold Clearance - Passed"
        if not activity:
            continue

        # Date detection. Preference order:
        #   1. Full slash date in the body (M/D/YY) — author's intent.
        #   2. Partial slash date in body (M/D, no year) + year from Sent
        #      header's long-form date.
        #   3. Long-form date from Sent header alone (e.g. "April 29, 2026").
        body_lines = [
            ln for ln in block if not _HEADER_LINE_RE.match(ln)
        ]
        body_text = "\n".join(body_lines)

        long_match = _LONG_DATE_RE.search(block_text)
        long_year = int(long_match.group(3)) if long_match else None

        date_str = None
        full_m = date_pattern.search(body_text)
        if full_m:
            date_str = full_m.group(1)
        else:
            partial_m = _PARTIAL_SLASH_RE.search(body_text)
            if partial_m and long_year is not None:
                month_p = int(partial_m.group(1))
                day_p = int(partial_m.group(2))
                if 1 <= month_p <= 12 and 1 <= day_p <= 31:
                    date_str = f"{month_p}/{day_p}/{str(long_year)[2:]}"
            if not date_str and long_match:
                month = _MONTH_TO_NUM[long_match.group(1)[:3].lower()]
                day = int(long_match.group(2))
                date_str = f"{month}/{day}/{str(long_year)[2:]}"
        if not date_str:
            continue

        # Normalize to M/D/YY (mirrors the line-by-line loop).
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                d = datetime.strptime(date_str, fmt)
                date_str = f"{d.month}/{d.day}/{str(d.year)[2:]}"
                break
            except ValueError:
                pass
        weekday = get_weekday(date_str)

        billing = sub_billing_default.get(matched_sub, "Billed Ins")
        if ("servpro paid" in block_lower
                or "billed servpro" in block_lower
                or "credit card" in block_lower):
            billing = "Billed Servpro"
        if ("passed" in block_lower
                and ("clear" in block_lower or "criteria" in block_lower)):
            full_activity = "Mold Clearance - Passed"
        else:
            full_activity = f"{activity} - {billing}"

        key = (date_str, full_activity, matched_sub)
        if key in seen:
            continue
        seen.add(key)
        out.append((date_str, weekday, full_activity, matched_sub))
    return out


def _is_no_answer(text, label_pattern):
    """True when `label_pattern` appears in `text` immediately followed
    by ': No' (i.e. the labeled-Q&A form used in initial inspection
    notes). Used to suppress activity-extra flags when the technician
    explicitly said *No* to that question — e.g. an "Equipment Placed:
    No" line should not surface "EQ placed" on the day's activity.

    Distinguishes a bare 'no' from words that start with 'no'
    ('noted', 'north') by requiring a non-letter character to follow.
    `label_pattern` is a regex fragment matched case-insensitively; the
    'no' check is also case-insensitive, so the input does NOT need to
    be lowercased ahead of time."""
    for m in re.finditer(label_pattern, text, re.IGNORECASE):
        after = text[m.end():].lstrip()
        if not after.startswith(":"):
            continue
        val = after[1:].lstrip().lower()
        if (val.startswith("no")
                and (len(val) == 2 or not val[2].isalpha())):
            return True
    return False


def parse_comments(raw):
    """
    Parse Trello comments into sub entries and daily log entries.
    Returns (sub_rows, log_rows) each a list of (date, weekday, activity, techs).
    """
    sub_rows = []
    log_rows = []

    # Known sub contractors. Keys are matched case-insensitively against
    # the lowered comment block — multiple keys can resolve to the same
    # vendor (e.g. "charles taylor" / "charlestaylor.com" / "cte" /
    # "ct environmental" all → Charles Taylor). When extending, add the
    # vendor's email-domain stem too — many vendor emails arrive as
    # automated reports and the body wording is sparse, so the domain
    # is often the most reliable signal.
    sub_keywords = {
        "safeguard":          "Safeguard",
        "adt":                "ADT",
        "rgz":                "RGZ Electric",
        "charles taylor":     "Charles Taylor",
        "charlestaylor.com":  "Charles Taylor",
        "ct environmental":   "Charles Taylor",
        "cte#":               "Charles Taylor",
        "cte ":               "Charles Taylor",
    }
    sub_billing_default = {
        "Safeguard":      "Billed Ins",
        "ADT":            "Billed Servpro",
        "RGZ Electric":   "Billed Servpro",
        "Charles Taylor": "Billed Servpro",
    }

    # Activity type detection
    activity_map = [
        (r"\binitial\s+inspection\b",  "Initial Inspection", True),
        (r"\bcontents?\b",             "Contents",           False),
        (r"\bpack\s*out\b|\bpack-out\b|\bpackout\b|\bPO\b", "Pack Out", False),
        (r"\bpack\s*back\b|\bpack-back\b|\bpackback\b|\bPB\b", "Pack Back", False),
        (r"\bdemo\b",                  "Demo",               False),
        (r"\bmonitor\b",               "Monitor",            True),
        # Equipment pickup — a standalone visit ("Pick up EQ - FB",
        # "EQ picked up", "Air scrubber pickup"). Its own log row so the
        # snapshot shows the EQ retrieval, not just an aside on another line.
        (r"\bpick(?:ed|ing)?[\s-]*up\s+(?:eq|equipment|air\s*scrubbers?|"
         r"dehus?|air\s*movers?)\b|"
         r"\b(?:eq|equipment|air\s*scrubbers?|dehus?|air\s*movers?)"
         r"[\s-]*pick(?:ed|ing)?[\s-]*up\b", "EQ Pickup", False),
        (r"\bmold\s+prep\b",           "Mold Prep",          False),
        (r"\btear[\s-]?down\b",        "Teardown",           False),
        (r"\babatement\b",             "Abatement",          False),
        (r"\brecon\b",                 "Recon",              False),
        (r"\breinspection\b",          "Reinspection",       True),
        # Cleaning — covers SERVPRO-tech cleaning visits AND vendor
        # cleaning callouts (Coit / Stanley Steemer / etc.). The
        # boundary excludes incidental words like "cleaning out the
        # emails" since \bclean(?:ing|[-\s]?up|[-\s]?out)\b requires
        # a recognized cleaning suffix or compound.
        (r"\bclean(?:ing|[-\s]?up|[-\s]?out)\b", "Cleaning",   False),
    ]

    sub_activity_map = [
        (r"asbestos",                  "Asbestos & Lead Testing"),
        (r"mold\s+clear",              "Mold Clearance Testing"),
        (r"clearance.*pass",           "Mold Clearance - Passed"),
        (r"alarm\s+wire|adt",          "Alarm Wire Repair"),
        # Cleaning vendors (Coit / Stanley Steemer / MasterClean etc.)
        # — when a sub-line mentions cleaning we label the activity
        # accordingly so the subs table reads "Vendor — Cleaning".
        (r"\bcarpet\s+clean|\bduct\s+clean|\bdeep\s+clean|"
         r"\bcleaning\s+service|\bclean[-\s]?up\s+crew", "Cleaning"),
    ]

    lines = raw.strip().splitlines()
    date_pattern = re.compile(r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b')

    # Abbreviation map for initials found in dispatch lines
    abbrev_map = {
        "PG": "PG", "JL": "JL", "FB": "FB", "ML": "ML", "ME": "ME",
        "GL": "GL", "PB": "PB", "AC": "AC", "AP": "AP",
    }
    # Single source of truth — read live from audit_logic so user-added
    # techs from the Tech Roster dialog are picked up without restarting.
    tech_pattern = audit_logic.TECH_PATTERN

    # Patterns that indicate this is an email body line — skip for activity detection
    email_skip = re.compile(
        r'^(from:|to:|subject:|sent:|cc:|regards|good morning|good afternoon|'
        r'good evening|sincerely|thank you|email sent|please advise|please note|'
        r'hi |hello|dear |per |we will|we have|i was|called|left voicemail|'
        r'spoke with|following up|please find|kind regards|\d{3}-\d{3})', re.IGNORECASE)

    # Words that disqualify a line even if it has a date + activity keyword
    disqualify = re.compile(
        r'to schedule|to confirm|regarding the|schedule for|scheduling|'
        r'voicemail|left message|front desk|obtain an update|possibly|'
        r'tentatively|perhaps|co-inspect|attorney|insured to schedule',
        re.IGNORECASE)

    seen_log_dates = {}

    # === Pre-scan: detect negated activities (e.g. "no contents team was needed") ===
    # Uses proximity matching: negation must be within ~4 words of the activity keyword
    # to avoid false positives like "No Xact note will be added due to missed Demo".
    cancelled = set()
    _cancel_map_raw = [
        (r'\bcontents?\b',      'Contents'),
        (r'\bdemo\b',           'Demo'),
        (r'\bmonitor\b',        'Monitor'),
        (r'\bmold\s*prep\b',    'Mold Prep'),
        (r'\btear[\s-]?down\b', 'Teardown'),
        (r'\babatement\b',      'Abatement'),
        (r'\brecon\b',          'Recon'),
        (r'\bclean(?:ing|[-\s]?up|[-\s]?out)\b', 'Cleaning'),
    ]
    _NEG = (r'(?:\bno\b|\bnot\s+needed\b|\bnot\s+done\b|\bwas\s+not\b|\bwasn\'t\b|'
            r'\bdid\s+not\b|\bdidn\'t\b|\bnot\s+required\b|\bnot\s+necessary\b|'
            r'\bwasn\'t\s+needed\b)')
    _CANCEL_RE = [
        (re.compile(
            rf'(?:{_NEG}(?:\s+\w+){{0,4}}\s+{pat}|{pat}(?:\s+\w+){{0,4}}\s+{_NEG})',
            re.IGNORECASE
        ), label)
        for pat, label in _cancel_map_raw
    ]
    ctx_date = None
    for _line in raw.splitlines():
        _line = _line.strip()
        if not _line:
            continue
        _dm = date_pattern.search(_line)
        if _dm:
            for _fmt in ("%m/%d/%y", "%m/%d/%Y"):
                try:
                    _d = datetime.strptime(_dm.group(1), _fmt)
                    ctx_date = f"{_d.month}/{_d.day}/{str(_d.year)[2:]}"
                    break
                except ValueError:
                    pass
        if ctx_date:
            for _cr, _label in _CANCEL_RE:
                if _cr.search(_line):
                    cancelled.add((ctx_date, _label))

    # Pre-clean lines
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line or len(line) > 100 or email_skip.match(line) or disqualify.search(line):
            clean_lines.append(None)
        else:
            clean_lines.append(line)

    # Most-recent dispatch date — lets an activity line with no date of
    # its own (e.g. a second activity stacked under one date header)
    # inherit the date from the line above instead of being dropped.
    last_date_str = None

    for idx, line in enumerate(clean_lines):
        if not line:
            continue

        date_match = date_pattern.search(line)
        if date_match:
            date_str = date_match.group(1)
        elif last_date_str:
            # Carry over only if this line clearly looks like a dispatch
            # line (has a known activity keyword near the start AND at
            # least one tech name). Stops random prose from inheriting.
            check = re.sub(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b',
                           '', line, flags=re.IGNORECASE).strip().lstrip('- ,')
            looks_like_dispatch = any(
                re.search(p, check[:20], re.IGNORECASE)
                for p, _, _ in activity_map
            ) and tech_pattern.search(line) is not None
            if not looks_like_dispatch:
                continue
            date_str = last_date_str
        else:
            continue

        # normalize to M/D/YY
        d = None
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                d = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                pass
        if d:
            date_str = f"{d.month}/{d.day}/{str(d.year)[2:]}"

        # If the line names a weekday that doesn't match the date, correct the date.
        # Fixes cases like "Saturday 4/10" when Saturday is actually 4/11.
        date_str = _align_date_to_weekday(date_str, line)

        # Remember as the carryover anchor for later activity-only lines.
        last_date_str = date_str

        weekday = get_weekday(date_str)

        # If this line is mostly just a date/weekday, look ahead for activity
        stripped = re.sub(date_pattern, '', line).strip()
        stripped = re.sub(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b', '', stripped, flags=re.IGNORECASE).strip()
        if len(stripped) < 4:
            # Date-only line — grab next non-None line as the activity line
            next_line = None
            for j in range(idx+1, min(idx+4, len(clean_lines))):
                if clean_lines[j]:
                    next_line = clean_lines[j]
                    break
            if next_line:
                line = next_line  # use next line for activity/tech parsing

        line_lower = line.lower()

        # --- Check if sub contractor line ---
        matched_sub = None
        for kw, sub_name in sub_keywords.items():
            if kw in line_lower:
                matched_sub = sub_name
                break

        if matched_sub:
            activity = ""
            for pattern, label in sub_activity_map:
                if re.search(pattern, line_lower):
                    activity = label
                    break
            if not activity:
                continue
            billing = sub_billing_default.get(matched_sub, "Billed Ins")
            if "servpro paid" in line_lower or "billed servpro" in line_lower or "credit card" in line_lower:
                billing = "Billed Servpro"
            if "pass" in line_lower and "clear" in line_lower:
                full_activity = "Mold Clearance - Passed"
            else:
                full_activity = f"{activity} - {billing}"
            sub_rows.append((date_str, weekday, full_activity, matched_sub))
            continue

        # --- Check if on-site work line ---
        # Strip date/weekday to find where activity keyword falls relative to line start
        check_line = re.sub(date_pattern, '', line).strip()
        check_line = re.sub(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b',
                            '', check_line, flags=re.IGNORECASE).strip()
        check_line = check_line.lstrip('- ,')

        # Collect ALL activity types that appear near the start of the line
        all_matches = []
        for pattern, label, initials in activity_map:
            m = re.search(pattern, check_line, re.IGNORECASE)
            if m and m.start() <= 15:
                all_matches.append((label, initials))

        if not all_matches:
            continue

        # Remove types explicitly negated for this date
        active_matches = [(lbl, init) for lbl, init in all_matches
                          if (date_str, lbl) not in cancelled]
        if not active_matches:
            continue

        matched_type = "/".join(lbl for lbl, _ in active_matches)
        is_initials  = active_matches[0][1]

        # Tech in parens marks a Monitor: e.g., "Contents - Brenda/Wendy (PG)"
        # means PG is monitoring while Brenda/Wendy do the contents work.
        # The parenthesized tech stays grouped in parens in the techs cell
        # ("Brenda, Wendy (PG)") and the activity gets a " (Monitor)" tag.
        paren_techs = []
        paren_tech_spans = []
        for pm in re.finditer(r'\(([^)]+)\)', line):
            inner = pm.group(1).strip()
            if tech_pattern.fullmatch(inner):
                paren_techs.append(inner)
                paren_tech_spans.append(pm.span())

        regular_techs = [
            m.group(0) for m in tech_pattern.finditer(line)
            if not any(s <= m.start() < e for s, e in paren_tech_spans)
        ]
        techs_str = fmt_techs(regular_techs, initials_only=is_initials)
        if paren_techs:
            suffix = "(" + ", ".join(paren_techs) + ")"
            techs_str = f"{techs_str} {suffix}" if techs_str else suffix

        # Build activity detail
        detail = ""
        if "first day" in line_lower or "(1st" in line_lower:
            detail = "(First day)"
        elif "completed" in line_lower or "complete" in line_lower:
            detail = "(completed)"

        extra = []
        if "mold" in line_lower and matched_type in ("Demo",):
            extra.append("mold found")
        if "offsite" in line_lower or "packout" in line_lower:
            extra.append("offsite packout")
        if "alarm" in line_lower and "wire" in line_lower:
            extra.append("alarm wire cut")
        if "adt" in line_lower:
            extra.append("referred to ADT")
        if "moisture" in line_lower:
            extra.append("moisture present")
        if "eq picked up" in line_lower or "pickup eq" in line_lower:
            extra.append("EQ picked up")
        if "clearance passed" in line_lower or "passed" in line_lower and "clear" in line_lower:
            extra.append("clearance passed")
        if "job closed" in line_lower or "closed" in line_lower:
            extra.append("job closed")
        if "slab" in line_lower:
            extra.append("slab leak")
        if (("eq placed" in line_lower or "equipment placed" in line_lower)
                and not _is_no_answer(line_lower,
                                       r'eq\s+placed|equipment\s+placed')):
            extra.append("EQ placed")

        if detail:
            activity_text = f"{matched_type} {detail}"
        else:
            activity_text = matched_type

        # Tech-in-parens implies Monitor — append " (Monitor)" unless the
        # activity already names Monitor (e.g. via Contents/Monitor combo).
        if paren_techs and "Monitor" not in matched_type:
            activity_text += " (Monitor)"

        if extra:
            activity_text += " - " + ", ".join(extra[:2])

        # Build dedup keys for each individual type
        def _key(lbl):
            return "Initial Inspection" if lbl == "Initial Inspection" else (date_str, lbl)

        keys = [_key(lbl) for lbl, _ in active_matches]

        if len(active_matches) > 1:
            # Combined line (e.g. Contents/Demo): skip if ANY type already seen
            if any(k in seen_log_dates for k in keys):
                continue
        else:
            # Single type: standard dedup
            if keys[0] in seen_log_dates:
                continue

        for k in keys:
            seen_log_dates[k] = (activity_text, techs_str)
        log_rows.append((date_str, weekday, activity_text, techs_str))

    # === Post-scan: attach note extras from non-activity lines ===
    NOTE_EXTRAS = [
        (r'\beq\s+picked\s+up\b|pickup\s+eq\b',             "EQ picked up"),
        (r'\bjob\s+closed\b|\bclosed\b',                     "job closed"),
        (r'\beq\s+placed\b|equipment\s+placed\b',            "EQ placed"),
        (r'\bclearance\s+pass',                              "clearance passed"),
        (r'\bmold\s+found\b',                                "mold found"),
        (r'\bmoisture\b',                                    "moisture present"),
        (r'\bslab\b',                                        "slab leak"),
        (r'\bcos\s+sign|certificate.*sign',                  "COS signed"),
        (r'\bscope\s+complet',                               "scope done"),
        (r'\boffsite\s+packout\b|packout\b',                 "offsite packout"),
    ]

    # Index mutable log_rows by date (first entry per date)
    log_rows = list(log_rows)
    log_idx = {}
    for i, (d, _, _, _) in enumerate(log_rows):
        if d not in log_idx:
            log_idx[d] = i

    ctx_date = None
    for note_line in raw.splitlines():
        note_line = note_line.strip()
        if not note_line:
            continue

        dm = date_pattern.search(note_line)
        if dm:
            for fmt in ("%m/%d/%y", "%m/%d/%Y"):
                try:
                    _d = datetime.strptime(dm.group(1), fmt)
                    ctx_date = f"{_d.month}/{_d.day}/{str(_d.year)[2:]}"
                    break
                except ValueError:
                    pass

        if not ctx_date or ctx_date not in log_idx:
            continue
        if email_skip.match(note_line) or len(note_line) > 120:
            continue

        nl = note_line.lower()

        # Skip lines that contain activity keywords (already handled in main loop)
        if any(re.search(p, nl) for p, _, _ in activity_map):
            continue

        new_extras = []
        for pat, label in NOTE_EXTRAS:
            if not re.search(pat, nl, re.IGNORECASE):
                continue
            # Suppress when the matched phrase is the LABEL of a
            # "<label>: No" Q&A — initial inspection notes use that
            # form heavily ("Equipment Placed: No", "Visible Mold
            # Present: No"). Without this guard the parser flagged
            # "EQ placed" on jobs that explicitly said no equipment.
            if _is_no_answer(nl, pat):
                continue
            new_extras.append(label)
        if not new_extras:
            continue

        idx = log_idx[ctx_date]
        d, wd, act, tech = log_rows[idx]

        # Count existing extras (items after " - ")
        if " - " in act:
            n_extras = len(act.split(" - ", 1)[1].split(","))
        else:
            n_extras = 0

        for label in new_extras:
            if label.lower() in act.lower() or n_extras >= 2:
                continue
            act = (act + ", " + label) if " - " in act else (act + " - " + label)
            n_extras += 1

        log_rows[idx] = (d, wd, act, tech)

    # Augment with sub-contractor entries hidden in email blocks where the
    # line-by-line parser couldn't see them (sub identity is on the From:
    # line, which email_skip discards before sub-detection runs).
    extra_subs = _extract_email_block_subs(
        raw, sub_keywords, sub_activity_map, sub_billing_default, date_pattern)
    existing = {(d, a, s) for d, _w, a, s in sub_rows}
    for d, w, a, s in extra_subs:
        if (d, a, s) not in existing:
            sub_rows.append((d, w, a, s))
            existing.add((d, a, s))

    # Sort by date
    def sort_key(row):
        try:
            return datetime.strptime(row[0], "%m/%d/%y")
        except ValueError:
            return datetime.min

    sub_rows.sort(key=sort_key)
    log_rows.sort(key=sort_key)

    return sub_rows, log_rows


# ── Structured job log from get_all_comments ─────────────────────────────
# parse_comments works on a concatenated text blob and needs a date ON each
# dispatch line. Real Trello threads (especially estimate-heavy commercial
# jobs) are mostly quoted EMAIL chains with no in-body dates — the field
# note "Air scrubber picked up" carries its date only in the COMMENT's
# timestamp. extract_job_log / eq_lifecycle consume the get_all_comments
# list (each {date, data.text, memberCreator.fullName}) so every event is
# stamped by its comment date, and quoted-email/proposal noise is dropped.

# A line that starts a quoted email chain — everything from here down in a
# comment is forwarded history, not the note the person just typed.
_EMAIL_QUOTE_RE = re.compile(
    r'^\s*(?:from:|sent:|to:|cc:|subject:|-+\s*original message|'
    r'on .+ wrote:|get outlook|sent from my )', re.IGNORECASE)
# Proposal / pricing language — a comment that reads like an estimate email
# describes work that MIGHT happen, not work performed. We still mine it for
# decision events (lost/hold) but never for field-work events (cleaning/demo).
_PROPOSAL_RE = re.compile(
    r'\$\s?\d[\d,]{2,}|\boption\s*#?\s*[1-4]\b|\bproposal\b|'
    r'\brevised\s+(?:estimate|pricing|scope)\b|\bbudget(?:ary)?\b|'
    r'\bestimated?\s+cost\b', re.IGNORECASE)

# Field-work events (only mined from non-proposal notes). (label, regex)
_JOBLOG_WORK_EVENTS = [
    ("Initial Inspection",
     r'\binitial\s+inspection\b|completed?\s+the\s+(?:site\s+)?inspection|'
     r'inspection\s+(?:field\s+)?template'),
    ("EQ placed",
     r'\beq\s+placed\b|equipment\s+placed\b|equipment\s+placed:\s*yes|'
     r'\b(?:air\s*scrubber|dehu(?:midifier)?|air\s*mover)s?\b[^.\n]{0,30}'
     r'(?:placed|set|in\s+the\b)'),
    ("EQ picked up",
     r'\beq\s+pick(?:ed)?\s*up\b|equipment\s+pick(?:ed)?\s*up|'
     r'\b(?:grabbed|removed|retrieved|collected)\b[^.\n]{0,25}\beq\b|'
     r'\b(?:air\s*scrubber|dehu(?:midifier)?|air\s*mover)s?\b[^.\n]{0,20}'
     r'pick(?:ed)?\s*up|pick(?:ed)?\s*up[^.\n]{0,20}'
     r'(?:air\s*scrubber|dehu|equipment)'),
    ("Reinspection",
     r'\bre[\s-]?inspection\s+(?:was\s+)?(?:completed|performed|done)\b|'
     r'\bcompleted\s+(?:a\s+)?re[\s-]?inspection\b|'
     r'^\s*re[\s-]?inspection\s+completed\b'),
    ("Teardown",
     r'\btear[\s-]?down\s+(?:was\s+)?(?:completed|performed|done)\b|'
     r'\b(?:completed|performed)\s+(?:the\s+)?tear[\s-]?down\b'),
    ("Pack Out",
     r'\b(?:pack[\s-]?out|content(?:s)?\s+manipulation)\s+'
     r'(?:was\s+)?(?:completed|performed|done)\b|'
     r'\b(?:completed|performed)\s+(?:the\s+)?(?:pack[\s-]?out|content(?:s)?\s+manipulation)\b'),
    ("Pack Back",
     r'\bpack[\s-]?(?:back|in)\s+(?:was\s+)?(?:completed|performed|done)\b|'
     r'\b(?:completed|performed)\s+(?:the\s+)?pack[\s-]?(?:back|in)\b'),
    ("Mold Clearance - Passed",
     r'\b(?:mold\s+)?(?:clearance|containment)\b[^.\n]{0,55}\bpass(?:ed)?\b|'
     r'\bpass(?:ed)?\b[^.\n]{0,35}\b(?:mold\s+)?clearance\b'),
    ("Mold Clearance - Failed",
     r'\b(?:mold\s+)?(?:clearance|containment)\b[^.\n]{0,55}\bfail(?:ed)?\b|'
     r'\bfail(?:ed)?\b[^.\n]{0,35}\b(?:mold\s+)?clearance\b'),
    ("Demo", r'\bdemo(?:lition|ed|\'d)?\b'),
    ("Monitor", r'\bmonitor(?:ing|ed)?\b|\bdrying\s+in\s+progress\b'),
    ("Cleaning", r'\bhepa\s+vac|detailed\s+clean|cleaning\s+(?:complete|done)'),
]

_PLANNING_RE = re.compile(
    r'\b(?:schedul(?:e|ed|ing)|dispatch|request(?:ed)?|need(?:s|ed)?\s+to|'
    r'will\s+(?:be|start|begin|perform)|plan(?:ned|ning)?|pending|approved?\s+to|'
    r'authorization\s+for|ready\s+by|tomorrow|next\s+(?:week|day))\b',
    re.IGNORECASE)
_COMPLETED_RE = re.compile(
    r'\b(?:completed?|performed|finished|done|picked\s+up|grabbed|retrieved|'
    r'collected|placed|set\s+up|in\s+progress|passed|failed|discovered)\b',
    re.IGNORECASE)


def _planning_only(text):
    """True for a request/future plan that does not also report completed work."""
    return bool(_PLANNING_RE.search(text) and not _COMPLETED_RE.search(text))


def _event_is_planning_only(text, pattern):
    """Check planning language near this event, not elsewhere in the comment.

    A common Trello update says "Demo completed. Monitor scheduled tomorrow."
    Looking at the whole comment would let the completed demo accidentally make
    the future monitor look completed too, so each match gets its own sentence-
    sized window.
    """
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    if not matches:
        return False
    for match in matches:
        left = max(text.rfind(".", 0, match.start()),
                   text.rfind("\n", 0, match.start()))
        right_candidates = [p for p in (text.find(".", match.end()),
                                        text.find("\n", match.end())) if p >= 0]
        right = min(right_candidates) if right_candidates else len(text)
        context = text[left + 1:right]
        if not _planning_only(context):
            return False
    return True
# Decision / status events (mined from EVERY note, incl. emails).
_JOBLOG_DECISION_EVENTS = [
    ("Job lost — went with another firm",
     r'another\s+(?:firm|company|contractor|vendor|restoration)|'
     r'mov(?:ed|ing)\s+(?:ahead|forward)\s+with\s+another|'
     r'go(?:ing|ne)?\s+with\s+another|went\s+with\s+another|'
     r'declined\s+(?:our|the)\s+(?:proposal|estimate)'),
    ("Cancelled", r'\bcancel(?:led|ed|ling)?\b|withdrawn|not\s+proceeding'),
    ("On hold",
     r'\bon\s*hold\b|plac(?:e|ed|ing)\s+on\s+hold|put\s+.*\bpause\b|'
     r'pause\s+until|hold\s+(?:the\s+)?(?:job|estimate|revised)'),
    ("Resumed", r'\boff\s+hold\b|resum(?:e|ed|ing)\b|take\s+off\s+hold'),
]


def _initials(name):
    """First+last initials from a full name ("Mark Escobar" → "ME"). Falls
    back to the first token's first two letters."""
    parts = [p for p in re.split(r'\s+', (name or "").strip()) if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _comment_dt(c):
    """Parse a get_all_comments action's ISO `date` to a naive datetime."""
    s = (c.get("date") or "")[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S",):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _fresh_text(c):
    """The note a person actually typed.

    Trello "forward" comments put an email-HEADER block (From/Sent/To/Cc/
    Subject) at the TOP, then the actual message, then often a DEEPER quoted
    chain. We skip a leading header block, keep the body, and stop at the
    next quote marker — so Dan's reply that opens with "From: Dan Danzig…"
    still yields "we moved ahead with another firm" instead of nothing."""
    raw = ((c.get("data") or {}).get("text") or "")
    lines = raw.splitlines()
    n = len(lines)
    i = 0
    while i < n and not lines[i].strip():
        i += 1
    # Skip a leading email-header block (contiguous header lines → blank).
    if i < n and _EMAIL_QUOTE_RE.match(lines[i]):
        while i < n and lines[i].strip():
            i += 1
        while i < n and not lines[i].strip():
            i += 1
    out = []
    for ln in lines[i:]:
        if _EMAIL_QUOTE_RE.match(ln):
            break  # deeper quoted message starts here
        out.append(ln)
    return "\n".join(out).strip()


def extract_job_log(comments):
    """Build a clean, dated job log from a get_all_comments list.

    Returns a list of dicts sorted oldest-first:
        {"date": "M/D/YY", "weekday": str, "activity": str, "who": initials}

    Each event is stamped with its COMMENT date (not an in-body date), so a
    bare "Air scrubber picked up" note is logged on the day it was posted.
    Quoted email chains are stripped; proposal/estimate emails contribute
    only decision events (lost / on-hold / cancelled), never field work — so
    a proposal that merely describes "HEPA cleaning" doesn't fake a cleaning
    visit. Identical (date, activity) pairs are de-duplicated."""
    rows, seen = [], set()
    for c in (comments or []):
        dt = _comment_dt(c)
        if dt is None:
            continue
        fresh = _fresh_text(c)
        if not fresh:
            continue
        who = _initials((c.get("memberCreator") or {}).get("fullName"))
        date_str = f"{dt.month}/{dt.day}/{str(dt.year)[2:]}"
        weekday = get_weekday(date_str)
        is_proposal = bool(_PROPOSAL_RE.search(fresh))
        events = list(_JOBLOG_DECISION_EVENTS)
        if not is_proposal:
            events = _JOBLOG_WORK_EVENTS + events
        for label, pat in events:
            if not re.search(pat, fresh, re.IGNORECASE):
                continue
            if ((label, pat) in _JOBLOG_WORK_EVENTS
                    and _event_is_planning_only(fresh, pat)):
                continue
            # Respect explicit "No" answers on the field template
            # (e.g. "Equipment Placed: No" must not log EQ placed).
            if label == "EQ placed" and _is_no_answer(
                    fresh.lower(), r'equipment\s+placed'):
                continue
            key = (date_str, label)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"date": date_str, "weekday": weekday,
                         "activity": label, "who": who})
    rows.sort(key=lambda r: (datetime.strptime(r["date"], "%m/%d/%y")
                             if re.match(r'\d', r["date"]) else datetime.min))
    return rows


def eq_lifecycle(comments):
    """Track equipment placed vs picked up across a job's comments.

    Returns {"placed": ["M/D/YY", ...], "picked_up": ["M/D/YY", ...],
             "outstanding": bool, "days_out": int|None}. `outstanding` is
    True when equipment was placed and never picked up; `days_out` is the
    age of the earliest un-recovered placement (caller passes today via the
    most recent comment, so no clock needed here — uses the latest comment
    date as 'now')."""
    placed, picked = [], []
    latest = None
    for c in (comments or []):
        dt = _comment_dt(c)
        if dt is None:
            continue
        latest = dt if (latest is None or dt > latest) else latest
        fresh = _fresh_text(c)
        if not fresh or _PROPOSAL_RE.search(fresh):
            continue
        ds = f"{dt.month}/{dt.day}/{str(dt.year)[2:]}"
        if re.search(_JOBLOG_WORK_EVENTS[2][1], fresh, re.IGNORECASE):
            picked.append((dt, ds))
        elif (re.search(_JOBLOG_WORK_EVENTS[1][1], fresh, re.IGNORECASE)
              and not _is_no_answer(fresh.lower(), r'equipment\s+placed')):
            placed.append((dt, ds))
    outstanding = len(placed) > len(picked)
    days_out = None
    if outstanding and placed and latest is not None:
        earliest_unrecovered = sorted(placed)[len(picked)][0]
        days_out = max(0, (latest - earliest_unrecovered).days)
    return {
        "placed":      [ds for _dt, ds in sorted(placed)],
        "picked_up":   [ds for _dt, ds in sorted(picked)],
        "outstanding": outstanding,
        "days_out":    days_out,
    }


_SCOPE_MATERIAL_RE = re.compile(
    # Materials / equipment / containment vocabulary
    r'\b(?:drywall|base\s*pf|floorpro|floor\s*pro|plastic|zipper|scrubber|dehu|'
    r'toe\s*kick|toekick|items?\s+removed|flooring\s+removed|sq\s*ft|sqft|'
    r'am\b|zippers?|floorpro|containment|insulation|laminate|tile|carpet|'
    r'cabinet|vanity|toilet|washer|dryer|jamb|jambs)\b|'
    # Generic scope action verbs — most lines in a scope start with one
    # of these (Removed vanity, Detached 2 doors, Door trim removed-28').
    # `\bremoved?\b` covers "remove" and "removed".
    r'\b(?:removed?|detached|demo|demoed|sealed|capped|cleaned|'
    r'sanded|primed|painted)\b|'
    # Square / linear-foot measurements
    r'\b\d+(?:\.\d+)?\s*(?:sqft|sq\.?\s*ft|sf|lf)\b|'
    # Feet/inches dimensions — straight OR curly quotes
    # (’ = ’, ” = ”). User notes pasted from Word /
    # iOS auto-curl, so the original ASCII-only regex missed them.
    r"\b\d+\s*['’”\"]"
    r"[\d'’”\"\sx]*",
    re.IGNORECASE
)
_SCOPE_DATE_RE    = re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b')
_SCOPE_WEEKDAY_RE = re.compile(
    r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b', re.IGNORECASE)
_SCOPE_EMAIL_RE   = re.compile(
    r'^(from:|to:|subject:|sent:|regards|good morning|good afternoon|sincerely|thank you)',
    re.IGNORECASE)
# Room/area vocabulary — a strong positive signal that a bare line is a
# ROOM HEADER (not a scope item or sub-point). Guarded by `not is_item`
# at the call site, so an item line that happens to mention a room word
# ("Removed Kitchen Cabinets") still stays an item.
_SCOPE_ROOM_RE = re.compile(
    r'\b(?:bath(?:room)?|kitchen|bed\s*room|bedroom|living|family|dining|'
    r'garage|hall(?:way)?|master|closet|laundry|office|den|basement|attic|'
    r'loft|foyer|entry(?:way)?|mud\s*room|pantry|nook|stair(?:s|way|well)?|'
    r'landing|porch|patio|deck|balcony|exterior|interior|unit|suite|room|'
    r'area|level|upstairs|downstairs|bonus|rec\s*room|utility|storage|'
    r'great\s*room|powder|sun\s*room|breakfast|study|nursery|garage)\b',
    re.IGNORECASE)
# A top-level scope action (removal / demo / tear-out). Used to decide
# where an indented sub-list ENDS — the first line like this resumes the
# main list beneath a room. Sub-points (component/quantity lines) don't
# carry these verbs, so they keep indenting under their "Foo:" header.
_SCOPE_RESUME_RE = re.compile(
    r'\b(remov\w*|demo\w*|tear\s*out|haul(?:ed)?)\b', re.IGNORECASE)


def _scope_item_kinds(items):
    """Classify each scope item for PDF indentation:
       'head' — a "Foo:" sub-list header (group label)
       'sub'  — an indented sub-point beneath the current header
       'item' — a normal top-level scope line

    A sub-list runs from a "Foo:" header (e.g. "Detached Appliances:",
    "Containment:") until a top-level removal/demo action — or another
    header / end of room — resumes the main list. Pure re-derivation from
    the flat item strings, so it survives the web save path (which strips
    items) without changing the room/items data contract."""
    kinds, in_sub = [], False
    for it in items:
        txt = str(it).strip()
        if txt.endswith(":"):
            kinds.append("head")
            in_sub = True
        elif in_sub and not _SCOPE_RESUME_RE.search(txt):
            kinds.append("sub")
        else:
            kinds.append("item")
            in_sub = False
    return kinds


def parse_scope(raw):
    """
    Detect a room-by-room scope block in Trello comments.
    Returns list of {"room": str, "items": [str]}, or [] if none found.
    """
    undated = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or len(line) > 80:
            undated.append(None)
            continue
        if (_SCOPE_DATE_RE.search(line) or _SCOPE_EMAIL_RE.match(line) or
                (_SCOPE_WEEKDAY_RE.search(line) and len(line) < 25)):
            undated.append(None)
            continue
        undated.append(line)

    # Split into blocks. Trello/Word pastes commonly double-space their
    # scope (one blank line between every entry), so a strict
    # split-on-any-None breaks every scope into 1-line blocks and the
    # ≥3-material check never trips. Tolerate single-line gaps within
    # a block — only break when we hit two or more consecutive Nones.
    blocks, cur, gap = [], [], 0
    for line in undated:
        if line is None:
            if cur:
                gap += 1
                if gap >= 2:
                    blocks.append(cur)
                    cur = []
                    gap = 0
        else:
            gap = 0
            cur.append(line)
    if cur:
        blocks.append(cur)

    # Find the block with the most material-matching lines
    best_block, best_count = None, 0
    for block in blocks:
        cnt = sum(1 for l in block if _SCOPE_MATERIAL_RE.search(l))
        if cnt > best_count:
            best_count, best_block = cnt, block

    if best_count < 3:
        return []

    # Group into rooms.
    #
    # Three signals say a line is an ITEM (not a room header):
    #   1. Matches the material vocabulary (drywall/sqft/vanity/etc)
    #   2. Contains a colon — `Drywall: 35 sqft` is the canonical item
    #      shape; "Items Removed:" is a sub-list header that's still an
    #      item under the current room.
    #   3. The previous line ended with a colon — the current line is
    #      a sub-list continuation (e.g. "1 door with trim" right after
    #      "Items Removed:"). This catches removal sub-items that lack
    #      material vocabulary.
    # A line is a ROOM HEADER only when none of the above apply AND it's
    # short AND has no digits (digits are a strong "this is an item with
    # a measurement / quantity" signal — "1 door with trim" / "2 doors"
    # / "Vanity (3 ft)" should never become room headers).
    rooms, current_room = [], None
    prev_ended_with_colon = False
    in_sublist = False
    for line in best_block:
        # Pure separators (──, ⸻, ---) hold a block together during the
        # split pass above but are neither a room nor an item — skip them.
        if not re.search(r'[A-Za-z0-9]', line):
            continue
        is_material = bool(_SCOPE_MATERIAL_RE.search(line))
        has_colon   = ":" in line
        has_digit   = any(c.isdigit() for c in line)
        is_short    = len(line) < 45
        ends_colon  = line.rstrip().endswith(":")
        is_bare     = not (is_material or has_colon or has_digit)
        # A line is an ITEM when it carries scope vocabulary, a colon, the
        # previous line opened a sub-list ("X:" then a bare line), OR we're
        # still inside a sub-list and this is a bare sub-point. That last
        # clause is the fix for multi-line sub-lists: "Detached Appliances:"
        # followed by "Microwave" / "Refrigerator" / "Dishwasher" — every
        # bare appliance stays an item instead of the 2nd-and-later ones
        # turning into empty room headers (which then got dropped).
        is_item = (is_material or has_colon or prev_ended_with_colon
                   or (in_sublist and is_bare))
        has_room_word = bool(_SCOPE_ROOM_RE.search(line))
        # A bare line is a ROOM only when it isn't an item, is short, has no
        # measurement digit, isn't mid-sub-list, AND either names a room or
        # the previous room already collected items (so a genuinely new room
        # is starting). This keeps note-style sub-headers like "Supported
        # Countertops" as items under the current room rather than spawning
        # an empty room that swallows the lines beneath it.
        room_ok = (has_room_word or current_room is None
                   or bool(current_room and current_room["items"]))
        is_room = ((not is_item) and is_short and (not has_digit)
                   and (not in_sublist) and room_ok)
        if is_room:
            if current_room:
                rooms.append(current_room)
            current_room = {"room": line.rstrip('.').strip(), "items": []}
            in_sublist = False
        else:
            if current_room is None:
                current_room = {"room": "General", "items": []}
            current_room["items"].append(line)
            # Sub-list state: a "X:" header opens one, a bare sub-point
            # keeps it open, a measured/material item closes it.
            if ends_colon:
                in_sublist = True
            elif in_sublist and is_bare:
                in_sublist = True
            else:
                in_sublist = False
        prev_ended_with_colon = ends_colon
    if current_room:
        rooms.append(current_room)

    return [r for r in rooms if r["items"]]


class _RoomTable(Table):
    """A scope-room table that knows it might span pages.

    Behavior:
      - Row 0 is the room header; rows 1..N are scope items.
      - `repeatRows=1` (set by `build_scope_pdf`) makes ReportLab put
        a copy of row 0 at the top of every page the table spans.
      - We override `split()` so the *continuation* half's repeated
        header is rewritten as "<RoomName> (cont.)" — that way the
        user can tell at a glance the room is continuing from the
        previous page rather than being a duplicate listing.

    Public attributes the constructor needs:
      - `room_name`  : the bare room title used to build the cont. label
      - `room_style` : the ParagraphStyle for the header so the cont.
                       version matches the original visually
    """

    def __init__(self, *args, room_name="", room_style=None, **kwargs):
        self._room_name  = room_name
        self._room_style = room_style
        super().__init__(*args, **kwargs)

    def split(self, availWidth, availHeight):
        result = super().split(availWidth, availHeight)
        # ReportLab returns [] (fits), [self] (can't split), or
        # [first, second] when it actually splits the table.
        if len(result) == 2:
            second = result[1]
            # ReportLab clones via self.__class__ during a split, so
            # `second` is also a _RoomTable but its constructor was
            # called via the parent's positional signature — meaning
            # `_room_name` / `_room_style` weren't passed. Forward
            # them explicitly so a second-stage split keeps working.
            second._room_name  = self._room_name
            second._room_style = self._room_style
            try:
                # repeatRows=1 placed a copy of row 0 at the top of
                # the continuation. Replace it with the cont. label.
                # We avoid stacking " (cont.)" on every page by always
                # building from the original `_room_name`, never from
                # whatever text is currently in row 0.
                if self._room_name and self._room_style is not None:
                    cont = Paragraph(f"{self._room_name} (cont.)",
                                      self._room_style)
                    second._cellvalues[0] = [cont]
            except (AttributeError, IndexError):
                pass
        return result


def build_scope_pdf(rooms, insured, out_path):
    """Generate a room-by-room scope PDF and write it to out_path."""
    _green = rl_colors.Color(0/255, 166/255, 81/255)
    _lgray = rl_colors.Color(0.93, 0.93, 0.93)
    _dgray = rl_colors.Color(0.5, 0.5, 0.5)

    styles = getSampleStyleSheet()
    def _s(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s = _s("ST", fontSize=16, fontName="Helvetica-Bold",
                 textColor=rl_colors.white, alignment=TA_CENTER)
    sub_s   = _s("SS", fontSize=9,  fontName="Helvetica",
                 textColor=rl_colors.Color(0.7, 0.9, 0.75), alignment=TA_CENTER)
    room_s  = _s("SR", fontSize=11, fontName="Helvetica-Bold",
                 textColor=rl_colors.Color(0.05, 0.05, 0.05),
                 spaceBefore=10, spaceAfter=3)
    item_s  = _s("SI", fontSize=9,  fontName="Helvetica",
                 leftIndent=14, spaceAfter=2)
    # Sub-list header ("Detached Appliances:") and its indented sub-points.
    subhead_s = _s("SHD", fontSize=9, fontName="Helvetica-Bold",
                   leftIndent=14, spaceBefore=1, spaceAfter=1)
    subitem_s = _s("SUB", fontSize=9, fontName="Helvetica",
                   leftIndent=34, textColor=_dgray, spaceAfter=2)

    today_str = datetime.today().strftime("%B %d, %Y")
    doc = SimpleDocTemplate(
        out_path, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch,  bottomMargin=0.75*inch,
    )
    story = []

    hdr = Table([
        [Paragraph("SERVPRO  ·  EMS Scope", title_s)],
        [Paragraph(f"{insured}  ·  {today_str}", sub_s)],
    ], colWidths=[7*inch])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), _green),
        ("TOPPADDING",    (0,0), (-1,0),  14),
        ("BOTTOMPADDING", (0,-1), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 0.18*inch))

    for room_data in rooms:
        # Build the room as a SINGLE table: row 0 is the header, the
        # rest are scope items. This guarantees the header stays with
        # its items — KeepTogether-around-a-Table sometimes
        # mismeasures combined height and lets a break slip between
        # the title and its first item (the user-reported "Bedroom on
        # page 1, items on page 2" symptom). `repeatRows=1` also
        # re-renders the header on every page if a long room's items
        # genuinely need to span pages — and `_RoomTable.split` swaps
        # the repeated header for "<Name> (cont.)" so the user can
        # tell the room is continuing rather than a fresh listing.
        data = [[Paragraph(room_data["room"], room_s)]]
        kinds = _scope_item_kinds(room_data["items"])
        for item, kind in zip(room_data["items"], kinds):
            txt = str(item).strip()
            if not txt:
                continue
            if kind == "head":
                data.append([Paragraph(txt, subhead_s)])
            elif kind == "sub":
                data.append([Paragraph("–  " + txt, subitem_s)])
            else:
                data.append([Paragraph(txt, item_s)])
        tbl = _RoomTable(data, colWidths=[7*inch], repeatRows=1,
                          room_name=room_data["room"], room_style=room_s)
        tbl.setStyle(TableStyle([
            # Header row — borderless, no extra background; let the
            # Paragraph style handle its own font/spacing.
            ("BACKGROUND",    (0, 0), (-1, 0),  rl_colors.white),
            ("LEFTPADDING",   (0, 0), (-1, 0),  0),
            ("RIGHTPADDING",  (0, 0), (-1, 0),  0),
            ("TOPPADDING",    (0, 0), (-1, 0),  4),
            ("BOTTOMPADDING", (0, 0), (-1, 0),  2),
            # Item rows — gray strip with thin border, same look the
            # original separate Table had.
            ("BACKGROUND",    (0, 1), (-1, -1), _lgray),
            ("LEFTPADDING",   (0, 1), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 1), (-1, -1), 10),
            ("TOPPADDING",    (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
            ("BOX",           (0, 1), (-1, -1),
             0.5, rl_colors.Color(0.8, 0.8, 0.8)),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.1*inch))

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_dgray)
        canvas.drawString(0.75*inch, 0.38*inch,
            f"SERVPRO EMS Scope  ·  {insured}  ·  {today_str}  ·  Confidential")
        canvas.drawRightString(7.75*inch, 0.38*inch, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _auto_size_da(existing) -> str:
    """Force font-size 0 (auto-size) in an AcroForm /DA string so long text
    shrinks to fit the field box instead of clipping. Preserves the font
    name from the existing /DA when present."""
    s = "" if existing is None else str(existing)
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    if "Tf" in s:
        return re.sub(r"(/[^\s]+)\s+[\d.]+\s+Tf", r"\1 0 Tf", s, count=1)
    return "/Helv 0 Tf 0 g"


def fill_pdf(data, output_path):
    template = pdfrw.PdfReader(_template())
    for page in template.pages:
        annots = page.get('/Annots')
        if not annots:
            continue
        for annot in annots:
            if annot.get('/Subtype') == '/Widget':
                key = annot.get('/T')
                if key:
                    k = key[1:-1]
                    if k in data:
                        upd = pdfrw.PdfDict(
                            V=pdfrw.objects.pdfstring.PdfString.encode(data[k]),
                            AP=pdfrw.PdfDict())
                        # Overflow-prone columns (Activity / Techs): auto-size
                        # the font so a long entry shrinks to fit the box
                        # rather than running off the edge (the fixed template
                        # boxes can't grow taller). Dates/weekdays keep their
                        # template font.
                        if ("activity" in k or "techs" in k):
                            upd.DA = pdfrw.objects.pdfstring.PdfString.encode(
                                _auto_size_da(annot.get('/DA')))
                        annot.update(upd)
    template.Root.AcroForm.update(pdfrw.PdfDict(NeedAppearances=pdfrw.PdfObject('true')))
    pdfrw.PdfWriter().write(output_path, template)


def _snapshot_office_line() -> str:
    """Best-effort office / franchise name for the snapshot header."""
    try:
        import config as _cfg
        c = _cfg.load()
        for key in ("franchise", "franchise_name", "office_name", "office"):
            v = (c.get(key) or "").strip() if isinstance(c, dict) else ""
            if v:
                return v
    except Exception:
        pass
    return "SERVPRO of Woodcrest / El Cerrito / Lake Mathews"


def render_snapshot(output_path, *, insured, carrier="", dol="",
                    first_visit="", cause="", subs=None, logs=None):
    """Render the EMS job snapshot as a fully rendered PDF (NOT the fillable
    template): a header block + Sub/Vendor Log + Daily Job Log as tables
    whose Activity/Techs cells WRAP and whose rows grow to fit — so nothing
    clips and long entries flow onto the next line. ReportLab paginates the
    logs naturally across as many pages as needed."""
    from reportlab.lib.pagesizes import letter as _letter
    from reportlab.lib.units import inch as _inch
    from reportlab.lib import colors as _colors
    from reportlab.lib.styles import (getSampleStyleSheet as _styles,
                                      ParagraphStyle as _PS)
    from reportlab.platypus import (SimpleDocTemplate as _Doc,
                                    Paragraph as _P, Spacer as _Sp,
                                    Table as _T, TableStyle as _TS)
    import xml.sax.saxutils as _sx

    subs = subs or []
    logs = logs or []
    base = _styles()

    def _s(name, **kw):
        kw.setdefault("parent", base["Normal"])
        return _PS(name, **kw)

    cell     = _s("sn_cell", fontName="Helvetica", fontSize=9, leading=11)
    hcell    = _s("sn_hcell", parent=cell, fontName="Helvetica-Bold")
    title_s  = _s("sn_title", fontName="Helvetica-Bold", fontSize=16, spaceAfter=1)
    office_s = _s("sn_office", fontSize=10,
                  textColor=_colors.HexColor("#666666"), alignment=2)
    sect_s   = _s("sn_sect", fontName="Helvetica-Bold", fontSize=11,
                  spaceBefore=10, spaceAfter=4)
    mlbl     = _s("sn_mlbl", fontName="Helvetica-Bold", fontSize=9)
    mval     = _s("sn_mval", fontSize=9)

    def P(t, st=cell):
        return _P(_sx.escape(str("" if t is None else t)), st)

    doc = _Doc(output_path, pagesize=_letter,
               leftMargin=0.6 * _inch, rightMargin=0.6 * _inch,
               topMargin=0.55 * _inch, bottomMargin=0.55 * _inch,
               title=f"{insured} — EMS Job Snapshot")
    # Title left, office name right-aligned on the same baseline (letterhead).
    _title_tbl = _T([[_P("EMS Job Snapshot", title_s),
                      _P(_sx.escape(_snapshot_office_line()), office_s)]],
                    colWidths=[4.7 * _inch, 2.6 * _inch])
    _title_tbl.setStyle(_TS([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story = [
        _title_tbl,
        _Sp(1, 0.14 * _inch),
    ]

    # Header meta — two label/value pairs per row.
    meta = [
        [P("Insured / Job", mlbl), P(insured, mval),
         P("Carrier / Claim", mlbl), P(carrier, mval)],
        [P("Date of Loss", mlbl), P(dol, mval),
         P("First Site Visit", mlbl), P(first_visit, mval)],
        [P("Cause / Category / Class", mlbl), P(cause, mval),
         P("Subs Used", mlbl), P("Yes" if subs else "No", mval)],
    ]
    mt = _T(meta, colWidths=[1.55 * _inch, 2.25 * _inch,
                             1.45 * _inch, 2.05 * _inch])
    mt.setStyle(_TS([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, _colors.HexColor("#E2E2E2")),
    ]))
    story.append(mt)

    col_w = [0.7 * _inch, 0.95 * _inch, 3.6 * _inch, 1.4 * _inch]
    header_row = [[P("Date", hcell), P("Weekday", hcell),
                   P("Activity / Status", hcell), P("Techs", hcell)]]
    tbl_style = _TS([
        ("BACKGROUND", (0, 0), (-1, 0), _colors.HexColor("#E0E0E0")),
        ("GRID", (0, 0), (-1, -1), 0.25, _colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])

    def _table_for(rows):
        body = header_row + [
            [P(r.get("date")), P(r.get("weekday")),
             P(r.get("activity")), P(r.get("techs"))] for r in rows]
        t = _T(body, colWidths=col_w, repeatRows=1)
        t.setStyle(tbl_style)
        return t

    if subs:
        story.append(_P("Sub / Vendor Log", sect_s))
        story.append(_table_for(subs))
    story.append(_P("Daily Job Log", sect_s))
    story.append(_table_for(logs) if logs
                 else _P("(no daily log entries)", cell))
    doc.build(story)


# Template field capacity — anything beyond this lands on the overflow
# continuation pages instead of being silently dropped. These match the
# fillable PDF's actual form fields (sub_date_1..8, log_date_1..53).
SNAPSHOT_TEMPLATE_SUBS_MAX = 8
SNAPSHOT_TEMPLATE_LOGS_MAX = 53


def append_overflow_pages(output_path, sub_overflow, log_overflow,
                           *, insured):
    """Append continuation page(s) to a generated snapshot PDF when the
    user logged more rows than the template's capacity. Empty overflow
    lists are a no-op.

    Uses ReportLab for the overflow tables (handles its own pagination
    so a long Daily Job Log spills onto multiple pages naturally), then
    pdfrw to merge the result onto the existing snapshot PDF — keeps
    the AcroForm-filled first page intact.

    Each row is `(date, weekday, activity, techs)`."""
    if not sub_overflow and not log_overflow:
        return

    import tempfile
    from reportlab.lib import colors as _rl_colors
    from reportlab.lib.pagesizes import letter as _rl_letter
    from reportlab.lib.units import inch as _rl_inch
    from reportlab.lib.styles import getSampleStyleSheet as _rl_styles
    from reportlab.platypus import (SimpleDocTemplate as _RLDoc,
                                      Paragraph as _RLPara,
                                      Spacer as _RLSpacer,
                                      Table as _RLTable,
                                      TableStyle as _RLTableStyle,
                                      PageBreak as _RLPageBreak)

    styles = _rl_styles()
    col_widths = [0.7 * _rl_inch, 0.95 * _rl_inch,
                   3.6 * _rl_inch, 1.4 * _rl_inch]
    header_row = [["Date", "Weekday", "Activity", "Techs"]]
    table_style = _RLTableStyle([
        ("FONT",       (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT",       (0, 0), (-1, 0),  "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0),
            _rl_colors.HexColor("#E0E0E0")),
        ("GRID",       (0, 0), (-1, -1), 0.25, _rl_colors.grey),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ])

    # Wrap every cell in a Paragraph so a long Activity / Techs value
    # WRAPS onto more lines and ReportLab auto-grows that row's height,
    # instead of a plain string clipping / spilling past the column edge.
    from reportlab.lib.styles import ParagraphStyle as _RLParaStyle
    import xml.sax.saxutils as _rl_sx
    _cell_style = _RLParaStyle("cont_cell", parent=styles["Normal"],
                               fontName="Helvetica", fontSize=9, leading=11)
    _hdr_style = _RLParaStyle("cont_hdr", parent=_cell_style,
                              fontName="Helvetica-Bold")

    def _cell(val, style=_cell_style):
        return _RLPara(_rl_sx.escape(str("" if val is None else val)), style)

    def _table_rows(rows):
        head = [[_cell(h, _hdr_style) for h in header_row[0]]]
        return head + [[_cell(c) for c in r] for r in rows]

    fd, cont_path = tempfile.mkstemp(suffix=".pdf",
                                      prefix="snapshot_overflow_")
    os.close(fd)
    try:
        doc = _RLDoc(
            cont_path, pagesize=_rl_letter,
            leftMargin=0.6 * _rl_inch, rightMargin=0.6 * _rl_inch,
            topMargin=0.6 * _rl_inch, bottomMargin=0.6 * _rl_inch,
            title=f"{insured} — Snapshot Continuation")
        story = [
            _RLPara(f"<b>{insured} — Snapshot (continued)</b>",
                     styles["Title"]),
            _RLSpacer(1, 0.2 * _rl_inch),
        ]
        if sub_overflow:
            story.append(_RLPara(
                f"<b>Sub / Vendor Log (continued — rows "
                f"{SNAPSHOT_TEMPLATE_SUBS_MAX + 1}+)</b>",
                styles["Heading2"]))
            tbl = _RLTable(_table_rows(sub_overflow),
                            colWidths=col_widths, repeatRows=1)
            tbl.setStyle(table_style)
            story.append(tbl)
            story.append(_RLSpacer(1, 0.25 * _rl_inch))
        if log_overflow:
            if sub_overflow:
                story.append(_RLPageBreak())
            story.append(_RLPara(
                f"<b>Daily Job Log (continued — rows "
                f"{SNAPSHOT_TEMPLATE_LOGS_MAX + 1}+)</b>",
                styles["Heading2"]))
            tbl = _RLTable(_table_rows(log_overflow),
                            colWidths=col_widths, repeatRows=1)
            tbl.setStyle(table_style)
            story.append(tbl)
        doc.build(story)

        # Merge: append continuation pages to the snapshot. We mutate
        # the underlying /Pages /Kids tree directly (not the lazy
        # .pages view, which doesn't propagate to the writer) and
        # re-parent each appended page so the page-tree stays
        # well-formed. Writing through `base` rather than constructing
        # a fresh PdfWriter keeps the original AcroForm metadata on
        # the first page intact so the filled values still render.
        base = pdfrw.PdfReader(output_path)
        cont = pdfrw.PdfReader(cont_path)
        base.Root.Pages.Kids.extend(cont.pages)
        base.Root.Pages.Count = len(base.Root.Pages.Kids)
        for p in cont.pages:
            p.Parent = base.Root.Pages
        pdfrw.PdfWriter().write(output_path, base)
    finally:
        try:
            os.remove(cont_path)
        except OSError:
            pass
