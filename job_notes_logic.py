"""Job-notes logic — stage detection, Trello-paste cleanup, note storage.

UI-free (no tkinter): the pure logic the Job Notes editor and the web
panels share. `job_notes_gui` re-exports every name below as a backward-
compat shim, so the Tk UI keeps working unchanged; web panels import from
here directly instead of reaching into the Tk module.

Extracted from job_notes_gui.py — see EMS_Tk_Extraction_Plan.md.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

import paths

_NOTES_ROOT = paths.data("notes")


# ── Stage detection ─────────────────────────────────────────────────────────
STAGES = [
    ("Initial Inspection", r"\b(initial\s+inspection|initial|inspection)\b",
        ["Initial pics", "Initial photo report"]),
    ("Mold Prep",          r"\bmold\s*prep\b",
        ["Mold Prep pics", "Post Mold Prep pics"]),
    ("Demo",               r"\bdemo\b",
        ["Demo pics", "Post pics"]),
    ("Monitor",            r"\bmonitor\b",
        []),
    ("Teardown",           r"\btear[\s-]?down\b",
        ["Post pics"]),
    ("Mold Clearance",     r"(\bmold\s+clear|clearance.*pass)",
        []),
    # Recon: only flag when recon work is actually starting/happening — bare
    # "Recon Services" / "Recon Board" / "Recon card" / "interested in recon"
    # are Trello handoff mentions and shouldn't move the timeline.
    ("Recon",
     r"\brecon\b\s+(?:start(?:ed|ing)?|begin(?:ning)?|begun|"
     r"in\s+progress|scheduled|crew|team|work(?:ing)?|phase|complete[d]?)"
     r"|\bmoved\s+(?:to|into)\s+recon\b"
     r"|\brecon\s+(?:walkthrough|estimate|estimator)\b",
        []),
    ("Reinspection",       r"\breinspection\b",
        ["Reinspection pics"]),
]


def parse_stages(text):
    """Returns list of stage labels detected in the text, in canonical order."""
    if not text:
        return []
    out = []
    for label, pat, _ in STAGES:
        if re.search(pat, text, re.IGNORECASE):
            out.append(label)
    return out


def expected_files(stages):
    """Union of expected files for each detected stage, in canonical order."""
    seen = set()
    out = []
    for label, _, files in STAGES:
        if label not in stages:
            continue
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
    return out


# ── Trello paste cleanup ────────────────────────────────────────────────────
# When the user copies comments out of Trello they come glued together with
# the per-comment "•\nReply\n•\nAdd link as attachment" boilerplate stuck
# between them. Splitting on the author+date headers and stripping the
# boilerplate makes the dump readable in the notes editor.

# "Laura Barajas Apr 27, 2026, 4:03 PM" — author and timestamp on the same
# line. Anchored to line bounds (re.MULTILINE) so an in-body fragment can't
# be eaten as a single fake header. Author may be 1+ words and any case.
_TRELLO_HEADER_RE = re.compile(
    r"^(?P<author>[A-Za-z][\w'.\-]*(?:[ \t]+[A-Za-z][\w'.\-]*)*)[ \t]+"
    r"(?P<date>[A-Z][a-z]{2}[ \t]+\d{1,2},[ \t]+\d{4},[ \t]+"
    r"\d{1,2}:\d{2}[ \t]*[AP]M)"
    # Trello adds " (edited)" after the timestamp on edited comments.
    r"(?P<edited>[ \t]+\(edited\))?"
    r"[ \t]*$",
    re.MULTILINE
)

# Trello also shows relative timestamps for recent comments — "1 hour ago",
# "5 minutes ago", "yesterday", "just now". We rewrite these to absolute
# `Mon DD, YYYY, H:MM AM/PM` headers so the rest of the cleaner can treat
# both formats identically.
_RELATIVE_HEADER_RE = re.compile(
    r"^(?P<author>[A-Za-z][\w'.\-]*(?:[ \t]+[A-Za-z][\w'.\-]*)*)[ \t]+"
    r"(?P<rel>just\s+now|yesterday|"
    r"\d+\s+(?:second|minute|hour|day|week)s?\s+ago)"
    # Optional "(edited)" — Trello tags edited comments this way.
    r"(?P<edited>[ \t]+\(edited\))?"
    r"[ \t]*$",
    re.MULTILINE | re.IGNORECASE
)

_REL_QTY_RE = re.compile(
    r"(\d+)\s+(second|minute|hour|day|week)s?\s+ago",
    re.IGNORECASE
)


def _resolve_relative_time(rel, now):
    """'1 hour ago' / 'yesterday' / 'just now' → datetime, or None."""
    s = rel.strip().lower()
    if s == "just now":
        return now
    if s == "yesterday":
        # Use start of yesterday so the rendered time isn't a misleading
        # "exactly 24h ago" — we don't actually know the time of day.
        return (now - timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0)
    m = _REL_QTY_RE.match(s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "second": timedelta(seconds=n),
        "minute": timedelta(minutes=n),
        "hour":   timedelta(hours=n),
        "day":    timedelta(days=n),
        "week":   timedelta(weeks=n),
    }[unit]
    return now - delta


def _format_trello_timestamp(ts):
    """Return ts as 'Apr 27, 2026, 4:03 PM' (no zero-pad on day or hour)."""
    return (
        f"{ts.strftime('%b')} {ts.day}, {ts.year}, "
        f"{ts.strftime('%I:%M %p').lstrip('0')}"
    )


def _rewrite_relative_headers(text, now):
    """Replace 'victoria 1 hour ago' with 'victoria Apr 30, 2026, 9:00 AM'.
    Preserves the trailing '(edited)' marker if present so the cleaned
    output keeps that signal."""
    def _sub(m):
        ts = _resolve_relative_time(m.group("rel"), now)
        if ts is None:
            return m.group(0)
        edited = " (edited)" if m.group("edited") else ""
        return f"{m.group('author')} {_format_trello_timestamp(ts)}{edited}"
    return _RELATIVE_HEADER_RE.sub(_sub, text)


def clean_trello_paste(text, now=None):
    """If `text` looks like a Trello comment dump, normalize it.

    Strips the per-comment "• Reply / • Add link as attachment" boilerplate
    and splits on author+date headers so each comment renders as:
        ─── Laura Barajas · Apr 27, 2026, 4:03 PM ───
        <message body>

    Trello relative timestamps ("1 hour ago", "yesterday", etc.) are
    resolved against `now` (defaults to datetime.now()) before splitting
    so they get an absolute timestamp in the output.

    Returns text unchanged when no Trello-style header is detected, so
    pasting non-Trello content (URLs, plain text) is a no-op.
    """
    if not text:
        return text
    if now is None:
        now = datetime.now()
    text = _rewrite_relative_headers(text, now)
    if not _TRELLO_HEADER_RE.search(text):
        return text

    # Reaction-count chrome — when someone reacts to a Trello comment the
    # emoji often doesn't make it through the clipboard, leaving a bare
    # digit on its own line right before the Reply chrome. Strip the
    # orphan count first (before the chrome itself disappears) so the
    # lookahead can still anchor on the chrome it precedes. Anchored to
    # the chrome so legit "1"/"2" body lines aren't wiped.
    cleaned = re.sub(
        r"^[ \t]*\d{1,3}[ \t]*\n+"
        r"(?=[ \t]*(?:•[ \t]*\n?[ \t]*)?(?:Reply|Add\s+link\s+as\s+attachment)\b)",
        "", text, flags=re.MULTILINE)
    # Drop the per-comment action chrome. Handles bullet+label on one line
    # ("• Reply") and split across two lines ("•\nReply"). "Reply and"
    # exists on some comments where Trello shows "Reply and add a link".
    cleaned = re.sub(
        r"•[ \t]*\n?[ \t]*Reply(?:[ \t]+and)?\b[^\n]*",
        "", cleaned)
    cleaned = re.sub(
        r"•[ \t]*\n?[ \t]*Add\s+link\s+as\s+attachment\b[^\n]*",
        "", cleaned)
    # Standalone chrome lines — Trello sometimes drops the bullet entirely
    # (especially right after a reaction). Match ONLY the exact chrome
    # forms so a body line starting with "Reply" ("Reply received.") or
    # the word "and" elsewhere isn't wiped. Three forms covered:
    #   "Reply"                                — bare label
    #   "Reply and add (a) link as attachment" — full chrome on one line
    #   "Add link as attachment"               — second half on its own
    cleaned = re.sub(
        r"^[ \t]*Reply[ \t]*$",
        "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(
        r"^[ \t]*Reply\s+and\s+(?:add\s+(?:a\s+)?)?link\s+as\s+attachment[ \t]*$",
        "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    cleaned = re.sub(
        r"^[ \t]*Add\s+link\s+as\s+attachment[ \t]*$",
        "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    # Collapse the trailing blank lines those substitutions leave behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    matches = list(_TRELLO_HEADER_RE.finditer(cleaned))
    if not matches:
        return cleaned.strip() + "\n"

    chunks = []
    pre = cleaned[:matches[0].start()].strip()
    if pre:
        chunks.append(pre)
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        body = cleaned[m.end():end].strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        # Plain "Author · Date" header — the editor styles each header
        # line as a colored band via a Tk text tag, so we don't need
        # ASCII-art separators in the saved file. Preserve "(edited)"
        # when Trello tagged this comment as modified.
        edited_suffix = " (edited)" if m.group("edited") else ""
        header = f"{m.group('author')} · {m.group('date')}{edited_suffix}"
        chunks.append(f"{header}\n{body}".rstrip() if body else header)
    return "\n\n".join(chunks).strip() + "\n"


# ── Storage ─────────────────────────────────────────────────────────────────

def _safe_filename(name):
    return "".join(c for c in name if c not in r'<>:"/\|?*').strip()


def _notes_path(year, client):
    # Normalize the year key. Callers pass int(2026), str("2026"), or the
    # raw X:\IE_Public folder name like "2026 Jobs" / "2025 LA FIRES" —
    # they must all resolve to the same folder under _NOTES_ROOT or
    # readers and writers drift apart (which is how `2026/` and
    # `2026 Jobs/` ended up with parallel sets of notes).
    key = str(year)
    m = re.search(r'\d{4}', key)
    if m:
        key = m.group(0)
    return os.path.join(_NOTES_ROOT, key, f"{_safe_filename(client)}.md")


def load_note(year, client):
    p = _notes_path(year, client)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return ""


def find_any_note_for_client(client):
    """Locate ANY .md note for `client`, regardless of year folder.

    Used by readers (hover popover, has-note checks) that don't have a
    reliable year — audit rows derive year from path basename which can
    mismatch the year the note was saved under (job carried over from
    prior year, user opened the note tool before the audit ran, etc.).
    Returns (year, text) for the most-recently-modified match, or
    (None, "") when nothing is found."""
    if not client:
        return None, ""
    safe = _safe_filename(client)
    if not safe:
        return None, ""
    if not os.path.isdir(_NOTES_ROOT):
        return None, ""
    best = None  # (mtime, year, path)
    try:
        with os.scandir(_NOTES_ROOT) as it:
            for ye in it:
                if not ye.is_dir():
                    continue
                p = os.path.join(ye.path, f"{safe}.md")
                if os.path.isfile(p):
                    try:
                        mt = os.path.getmtime(p)
                    except OSError:
                        mt = 0
                    if best is None or mt > best[0]:
                        best = (mt, ye.name, p)
    except OSError:
        return None, ""
    if best is None:
        return None, ""
    try:
        with open(best[2], encoding="utf-8") as f:
            return best[1], f.read()
    except OSError:
        return best[1], ""


def save_note(year, client, text):
    p = _notes_path(year, client)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def has_note(year, client):
    """True if a saved .md note exists for this (year, client)."""
    return os.path.isfile(_notes_path(year, client))


def has_any_note_for_client(client):
    """True if any .md note exists for `client` in ANY year folder.

    Used by callers that don't have a reliable year (or where the year
    they have can mismatch the year the note was saved under). Cheaper
    than `find_any_note_for_client` — early-exits on first match and
    doesn't read file contents."""
    if not client:
        return False
    safe = _safe_filename(client)
    if not safe or not os.path.isdir(_NOTES_ROOT):
        return False
    try:
        with os.scandir(_NOTES_ROOT) as it:
            for ye in it:
                if not ye.is_dir():
                    continue
                if os.path.isfile(os.path.join(ye.path, f"{safe}.md")):
                    return True
    except OSError:
        pass
    return False


def list_saved_notes():
    """[(year, client, mtime), ...] sorted newest-first."""
    out = []
    if not os.path.isdir(_NOTES_ROOT):
        return out
    with os.scandir(_NOTES_ROOT) as it:
        years = [ye for ye in it if ye.is_dir()]
    for ye in years:
        try:
            with os.scandir(ye.path) as it_y:
                for ne in it_y:
                    if ne.is_file() and ne.name.endswith(".md"):
                        try:
                            mtime = ne.stat().st_mtime
                        except OSError:
                            mtime = 0
                        out.append((ye.name, ne.name[:-3], mtime))
        except OSError:
            pass
    out.sort(key=lambda r: -r[2])
    return out
