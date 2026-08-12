"""Initial Inspection field-template parser.

Techs file initial inspections in a fixed field template (Date / Time /
Met With / Cause of Loss / Category / ...). The raw notes that land on
Trello are messy — some fields are filled in, others are left as the
literal "Yes / No" prompt with one side struck through, others are
blank. The snapshot's "Trello Summary" card was previously showing
just `Activities: Initial Inspection` for these — useful but loses
every captured field.

This module pulls the filled fields out of each initial-inspection
block so the summary card can list them cleanly:

    parse_initial_inspection_notes(raw) -> list[dict]
        each dict: {label -> value} for one inspection block

    format_initial_notes(parsed) -> str
        multi-line, presentation-ready string for the summary card

Design notes:
- We DON'T require the full template — partial / abbreviated fields
  are common. Anything labeled-and-non-empty surfaces.
- "Yes / No" prompts where one side has text after the slash
  resolve to that side (e.g. "Photos Taken: Yes /" → "Yes").
- Blank-value lines are skipped (we don't want a wall of empty labels).
- Multiple inspection blocks in one comment thread are returned
  separately so the UI can show each on its own day.
"""
from __future__ import annotations

import re


# Labels recognized inside an initial-inspection block. Order matters
# for the rendered output (we walk this list to keep field order stable
# regardless of how the tech typed them). Each entry is
# (canonical_label, [regex aliases]). The first alias is the
# user-facing label.
_FIELDS = [
    ("Date",               [r"^date"]),
    ("Time",               [r"^time of inspections?",
                             r"^time"]),
    ("Met With",           [r"^met with"]),
    ("Cause of Loss",      [r"^cause of loss(?:\s*\(col\))?",
                             r"^col\b"]),
    ("Category",           [r"^category(?:\s*\(cat\))?",
                             r"^cat\b"]),
    ("Class",              [r"^class\b"]),
    ("Plumbing Repairs",   [r"^plumbing repairs(?: completed)?"]),
    ("Leak Detection",     [r"^leak detection(?: recommended)?"]),
    ("Re-inspection",      [r"^re[\s-]?inspection(?: needed)?"]),
    ("Water Heater Temp",  [r"^water heater temp(?: set)?"]),
    ("Levels Affected",    [r"^number of levels affected",
                             r"^levels affected"]),
    ("Upstairs",           [r"^upstairs"]),
    ("Downstairs",         [r"^downstairs"]),
    ("Asbestos/Lead Test", [r"^asbestos/lead testing(?: needed)?",
                             r"^asbestos testing"]),
    ("Test Areas",         [r"^areas/materials needing testing",
                             r"^materials needing testing"]),
    ("Packout Required",   [r"^packout required",
                             r"^pack[\s-]?out required"]),
    ("Content Manipulation", [r"^content manipulation(?: done)?"]),
    ("Storage Type",       [r"^storage type"]),
    ("Storage Location",   [r"^where are contents being stored",
                             r"^contents being stored"]),
    ("Visible Mold",       [r"^visible mold(?: present)?"]),
    ("Mold Rooms",         [r"^rooms affected"]),
    ("Mold Sq Ft",         [r"^greater or less than 10 sq ft",
                             r"^mold sq ft"]),
    ("Equipment Placed",   [r"^equipment placed"]),
    ("Equipment Type",     [r"^type & quantity(?:\s*\(list by room\))?",
                             r"^equipment type"]),
    ("Specialty EQ",       [r"^specialty eq(?: and why)?"]),
    ("Signed Today",       [r"^signed today"]),
    ("Paperwork Types",    [r"^types\s*\(wa,?\s*cos.*\)",
                             r"^paperwork types"]),
    ("Customer Concerns",  [r"^customer concerns(?:\s*/\s*notes)?"]),
    ("Photos Taken",       [r"^photos taken"]),
    ("Video Taken",        [r"^video taken"]),
    ("DocuSketch Done",    [r"^docusketch(?: completed)?"]),
    ("Additional Notes",   [r"^additional field notes(?:\s*/\s*observations)?",
                             r"^additional notes"]),
]

# Compile aliases into a single (label, compiled-regex) list — first
# match wins, so more specific aliases must come before generic ones
# (e.g. "category (cat)" before "cat"). The field list above is already
# ordered that way.
_COMPILED_FIELDS = [
    (label, [re.compile(a, re.IGNORECASE) for a in aliases])
    for label, aliases in _FIELDS
]


# A line "X: value" matches this — splits the label from the value.
# Allows whitespace before the colon ("Content Manipulation :"). The
# value capture is greedy to the end of line.
_LABEL_LINE_RE = re.compile(r"^([^:]{2,60}?)\s*:\s*(.*)$")

# Section headers in the template are ALL CAPS — STRUCTURE & DAMAGE
# SUMMARY, TESTING, CONTENTS, MOLD, EQUIPMENT, PAPERWORK, OFFICE
# FOLLOW-UP. They contain no lowercase letters and at least one
# alphabetic char. Used as a hard boundary so a continuation paragraph
# under one field doesn't bleed into the next section.
_SECTION_HEADER_RE = re.compile(
    r"^[A-Z0-9 &/()\-,.'\"–—]{3,}$")

# Initial-inspection block headers we look for. A block starts at any
# of these lines and runs until the next block start or end of text.
_BLOCK_START_RE = re.compile(
    r"^\**\s*(?:initial\s+notes?|initial\s+inspection"
    r"|initial\s+inspection.*field\s+template"
    # Techs also file the report under this heading, sometimes with a
    # budgetary-estimate tail. Without it the block was only found by the
    # count-the-labels fallback, which needs four recognised labels in
    # one comment — and these reports carry Date / Time / Cause of Loss
    # and then prose, so they fell one short and the arrival time was
    # lost even though it was written down plainly.
    r"|preliminary\s+inspection\s+report.*"
    r")\s*\**\s*$",
    re.IGNORECASE)


# Email-body markers that signal we've left the initial-notes block and
# entered something else (adjuster-update email, internal comment,
# etc.). Used to terminate any open free-text continuation so a value
# like Downstairs doesn't vacuum the rest of the file. Substring match
# (case-insensitive) on the line head.
_EMAIL_BODY_MARKERS = (
    "from:",         # email header re-quote
    "to:",
    "cc:",
    "sent:",
    "subject:",
    "regards",
    "thank you",
    "email sent to",
    "please copy",   # "Please copy & paste the link below..."
    "please advise",
    "please be advised",
    "please note,",
    "good afternoon",
    "good morning",
    "[https://",     # markdown link to vidyard/docusketch
    "[mailto:",
)


def _is_email_body_marker(line: str) -> bool:
    low = line.strip().lower()
    if not low:
        return False
    return any(low.startswith(m) for m in _EMAIL_BODY_MARKERS)


# Trello comment-author timestamp lines — "<name> · <date>, <time>" or
# "<name> - <date>, <time>". Strong signal we've left the notes block
# and entered a different comment. Examples:
#   "victoria · May 20, 2026, 11:32 AM"
#   "Laura Barajas · Apr 22, 2026, 12:27 PM"
#   "Mark Escobar - Apr 22, 2026, 3:13 PM"
_COMMENT_AUTHOR_RE = re.compile(
    r"^[A-Za-z][A-Za-z .'’\-]{1,40}\s*[·\-–]\s*"
    r"[A-Z][a-z]{2}\s+\d{1,2},\s*\d{4}\b",
    re.IGNORECASE)


# Max characters we'll let a single field's continuation accumulate.
# Initial-inspection values are typically a few words to a short list;
# anything past this is almost certainly bleed from an unrelated
# comment / email body. Acts as a defensive cap so even if every other
# guard fails, one field can't swallow the rest of the document.
_MAX_CONTINUATION_CHARS = 280


def _resolve_yes_no(value: str) -> str:
    """Normalize Yes/No prompts.

    "Yes /"      → "Yes"        (other side struck off)
    "/ No"       → "No"
    ": / No"     → "No"
    "Yes / No"   → ""           (unanswered — drop)
    "No / Yes"   → ""
    "Yes"        → "Yes"
    "No"         → "No"
    "fridge"     → "fridge"     (free text — pass through)

    Returns "" when the field is effectively unanswered."""
    v = (value or "").strip()
    if not v:
        return ""
    # Normalize internal whitespace so "Yes  /  No" matches "Yes / No".
    norm = re.sub(r"\s+", " ", v)
    low = norm.lower()
    # Unanswered: both options still present.
    if low in {"yes / no", "no / yes", "/ yes / no", "yes / no /"}:
        return ""
    # One side struck off — keep the side with text.
    m = re.match(r"^(yes|no)\s*/\s*$", low)
    if m:
        return m.group(1).capitalize()
    m = re.match(r"^/\s*(yes|no)$", low)
    if m:
        return m.group(1).capitalize()
    # Bare yes or no.
    if low in {"yes", "no"}:
        return low.capitalize()
    # Otherwise it's free text — return as-is (preserve original spacing
    # of the user input, just strip leading/trailing).
    return v


def _match_label(text: str):
    """Return (canonical_label, remainder) when `text` starts with a
    known initial-inspection field label, else None.

    `text` should already be lowercase-normalized? No — we let the
    regexes use IGNORECASE so the caller can pass the raw line head."""
    head = text.strip()
    for label, patterns in _COMPILED_FIELDS:
        for p in patterns:
            m = p.match(head)
            if m:
                return label, head[m.end():].lstrip(" :")
    return None


def _parse_one_block(lines: list[str]) -> dict:
    """Walk one block's worth of lines and pull (label -> value) pairs.

    Inline secondary fields ("Category (CAT): 2  Class: 2") are split
    so both Category and Class surface. Multi-word values that span
    until the next label (e.g. an Additional Notes paragraph) are
    captured by collapsing trailing lines into the previous field
    until we hit another known label."""
    out: dict[str, str] = {}
    current_label: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            # Blank line — within an inspection block these are visual
            # spacing between sections, NOT a value boundary. The
            # template has blank gaps after every header, so resetting
            # current_label here would strand any continuation paragraph
            # (e.g. the free-text body that follows "Additional Field
            # Notes / Observations:" — typically separated by a blank
            # line from the label).
            continue

        # Try a `Label: value` parse first. _LABEL_LINE_RE is permissive,
        # so we re-verify the label against our known set.
        m = _LABEL_LINE_RE.match(line)
        if m:
            label_text, value = m.group(1), m.group(2)
            matched = _match_label(label_text)
            if matched:
                canon, _rest = matched
                value = value.strip()
                # Inline secondary label split: scan the value for
                # ` <KnownLabel>:` so "2 Class: 2" → ("Category", "2") +
                # ("Class", "2"). Only one extra split per line — deeper
                # nesting is uncommon and would risk false positives.
                inline = _find_inline_split(value)
                if inline:
                    primary_val, second_label, second_val = inline
                    if primary_val:
                        primary = _resolve_yes_no(primary_val)
                        if primary:
                            out[canon] = primary
                    sec = _resolve_yes_no(second_val)
                    if sec:
                        out[second_label] = sec
                    current_label = second_label
                else:
                    resolved = _resolve_yes_no(value)
                    if resolved:
                        out[canon] = resolved
                    current_label = canon
                continue
            # Line is colon-labeled BUT not a known field (e.g.
            # "Areas Affected:" — a structural sub-header in the
            # template that doesn't store a value, or some unrelated
            # email body label). Break the continuation so the
            # previous field doesn't keep absorbing.
            current_label = None
            continue

        # Not a colon-labeled line. Sub-cases in priority order:
        # (a) ALL-CAPS section header (STRUCTURE & DAMAGE SUMMARY,
        #     TESTING, MOLD, EQUIPMENT, PAPERWORK, OFFICE FOLLOW-UP).
        # (b) Email-body marker (From:/To:/Subject:/Regards/etc.) —
        #     means we've left the initial-notes block and entered an
        #     adjuster-update email or sign-off. Without this guard,
        #     Trello pastes that bundle the notes + the carrier email
        #     vacuum the email body into whatever the last field was
        #     (Downstairs was the loud reporter).
        # (c) Line starts with a known label even without a colon
        #     ("Met With (Insured" — tech forgot to close the paren and
        #     never typed the colon). Treat as a new (empty) field.
        # (d) Genuine continuation of the previous field's value
        #     (free-text paragraph after Additional Notes:).
        if _SECTION_HEADER_RE.match(line):
            current_label = None
            continue
        if _is_email_body_marker(line):
            current_label = None
            continue
        if _COMMENT_AUTHOR_RE.match(line):
            # Trello comment-author timestamp ("victoria · May 20,
            # 2026, 11:32 AM"). Means the current Trello paste has
            # moved on to a different comment — stop accumulating into
            # whatever field was last open.
            current_label = None
            continue
        bare_match = _match_label(line)
        if bare_match:
            current_label = None
            continue
        if current_label:
            existing = out.get(current_label, "")
            # Defensive cap — a single field shouldn't accumulate more
            # than _MAX_CONTINUATION_CHARS of free text. Past that
            # we're almost certainly absorbing an unrelated paragraph
            # the other guards above missed.
            if len(existing) >= _MAX_CONTINUATION_CHARS:
                current_label = None
                continue
            joined = f"{existing} {line}".strip() if existing else line
            # _resolve_yes_no is idempotent on free text.
            out[current_label] = _resolve_yes_no(joined) or joined

    return out


def _find_inline_split(value: str):
    """If `value` contains a second known label inline (`"2 Class: 2"`),
    return (primary_value, second_label, second_value). Otherwise None."""
    if ":" not in value:
        return None
    # Try every position of " <word>:" — first hit wins.
    for m in re.finditer(r"\s+([A-Za-z][A-Za-z &/()-]{1,40}?):", value):
        candidate = m.group(1)
        matched = _match_label(candidate)
        if matched:
            label, _rest = matched
            primary = value[:m.start()].strip()
            second = value[m.end():].strip()
            return primary, label, second
    return None


def parse_initial_inspection_notes(raw: str) -> list[dict]:
    """Find every initial-inspection block in `raw` and return a list
    of parsed field dicts.

    Returns []:
        - When raw is empty / None
        - When no recognizable block header is present

    The first match for each canonical label wins within a block, so
    techs editing the template inline can rely on top-down precedence."""
    if not raw or not raw.strip():
        return []
    lines = raw.splitlines()
    # Locate block start indexes. A block runs from a start line to the
    # next start (or EOF). When no explicit "Initial notes" header is
    # present but the body still has a Date: line + several known
    # labels, we assume the whole text is one block (common when a
    # tech pastes the filled template without the title).
    starts = [i for i, ln in enumerate(lines) if _BLOCK_START_RE.match(ln.strip())]
    if not starts:
        # Heuristic: any "Date:" line plus at least 3 other recognized
        # labels in the same text → treat whole thing as one block.
        seen_labels = 0
        for ln in lines:
            m = _LABEL_LINE_RE.match(ln.strip())
            if m and _match_label(m.group(1)):
                seen_labels += 1
                if seen_labels >= 4:
                    break
        if seen_labels < 4:
            return []
        starts = [0]

    blocks: list[dict] = []
    for k, idx in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        # Drop the header line itself when we recognized one.
        if _BLOCK_START_RE.match(lines[idx].strip()):
            block_lines = lines[idx + 1:end]
        else:
            block_lines = lines[idx:end]
        parsed = _parse_one_block(block_lines)
        # Only keep blocks that captured at least one meaningful field —
        # avoids polluting the summary with empty parses on stray
        # "Initial Inspection" headers (e.g. Trello checklist labels).
        if parsed:
            blocks.append(parsed)
    return blocks


# Fields that make a block genuinely useful as an inspection report.
# Used to score candidates: a block naming the date AND the arrival time
# is the tech's report; one with neither is something else that happened
# to trip the label heuristic.
_SCORE_FIELDS = ("Date", "Time", "Met With", "Cause of Loss", "Category")


def best_initial_block(texts) -> dict:
    """The most complete initial-inspection block across several texts.

    Callers used to join every comment on a card into one string and
    parse the lump, taking whichever block came out first. Two things
    went wrong. Comments arrive NEWEST-first, so an unrelated later
    comment that tripped the label heuristic beat the tech's actual
    report — and joining across comment boundaries let the tail of one
    comment and the head of the next form a block nobody wrote.

    Parsing each comment on its own and scoring them fixes both: the
    block naming the most inspection fields wins, ties going to the one
    that has an arrival Time, since recovering that is the point.
    Returns {} when nothing qualifies.
    """
    best, best_score = {}, -1
    for raw in (texts or []):
        if not raw or not str(raw).strip():
            continue
        try:
            blocks = parse_initial_inspection_notes(str(raw))
        except Exception:
            continue
        for b in blocks or []:
            score = sum(1 for k in _SCORE_FIELDS
                        if str(b.get(k) or "").strip())
            if str(b.get("Time") or "").strip():
                score += 1        # the tie-break, and the point of this
            if score > best_score:
                best, best_score = b, score
    return best


def format_initial_notes(parsed: list[dict]) -> str:
    """Render parsed blocks as a multi-line string for the summary card.

    Returns "" when there's nothing to show (caller can use truthiness
    to skip the section)."""
    if not parsed:
        return ""
    # Walk _FIELDS so output ordering is stable.
    label_order = [label for label, _ in _FIELDS]
    lines: list[str] = []
    for i, block in enumerate(parsed):
        if len(parsed) > 1:
            header = f"Inspection {i + 1}"
            if block.get("Date"):
                header += f" ({block['Date']})"
            lines.append(header + ":")
        for label in label_order:
            v = block.get(label)
            if v:
                lines.append(f"  • {label}: {v}")
    return "\n".join(lines)
