"""Pasted-XactAnalysis-notes parser + open-commitment detector.

XactAnalysis (XA) has no public API we can hit — billing/status follow-ups
that should appear in XA are entered manually through their web UI, and
when they DON'T appear, there's no programmatic way to detect the gap.

The workflow this module supports: the user pastes the raw text of a job's
XA notes panel into a Hygiene-tab textbox; we parse it into structured
records and flag jobs whose latest note contains an open verbal commitment
("billing to follow", "scheduled", "underway", "pending …") that hasn't
been closed by a subsequent note.

Pure logic — no GUI. The Hygiene panel wires the paste-in field, calls
parse_xa_notes() on the text, and feeds the parsed list into
analyze_notes() to decide whether the job belongs in the "📝 XA gap"
section.

CLI smoke test:
    python xa_notes.py paste.txt
        -> dump parsed notes + open-commitment summary
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any


# ── Tunables ────────────────────────────────────────────────────────────────

# Open-commitment phrases. Each entry: (regex, short_label, what_closes_it).
# `what_closes_it` is a regex of phrases that — if found in a NEWER note —
# we treat the commitment as closed. Empty tuple = nothing closes it
# automatically (always flag if it's the latest note).
_COMMITMENT_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # Billing follow-ups — the most-flagged miss in user's review.
    (r"\bbilling to follow\b", "billing-to-follow",
     (r"\binvoice\b", r"\bbilling (?:sent|posted|emailed)\b",
      r"\bfinal billing\b", r"\bcollected\b")),
    (r"\bto follow\b", "to-follow",
     (r"\bcompleted?\b", r"\bachieved\b", r"\bpassed?\b")),

    # Schedule commitments — fire when a future date was committed and the
    # subsequent "completed/performed" note never materialized.
    (r"\bscheduled to (?:commence|begin|start)\b", "scheduled-start",
     (r"\bcommence\w*\b", r"\bbegan?\b", r"\bcrews? en route\b",
      r"\bin progress\b")),
    (r"\bscheduled\b", "scheduled",
     (r"\bcompleted?\b", r"\bperformed\b", r"\bin progress\b")),
    (r"\bto be dispatched\b", "to-be-dispatched",
     (r"\bdispatched\b", r"\bcommenc\w+\b", r"\bperformed\b")),

    # State commitments — "underway" / "in progress" should be closed by
    # a "completed" / "achieved" / "passed" note.
    (r"\bdrying underway\b", "drying-underway",
     (r"\bdrying (?:achieved|complete[d]?)\b", r"\bteardown\b",
      r"\bdry time\b")),
    (r"\bdrying in progress\b", "drying-in-progress",
     (r"\bdrying (?:achieved|complete[d]?)\b", r"\bteardown\b")),
    (r"\bunderway\b", "underway",
     (r"\bcompleted?\b", r"\bachieved\b")),
    (r"\bin progress\b", "in-progress",
     (r"\bcompleted?\b", r"\bachieved\b", r"\bdone\b")),

    # Open questions / pending items.
    (r"\bpending mold clearance\b", "pending-mold-clearance",
     (r"\bmold clearance (?:pass|passed|received)\b",
      r"\bclearance report\b")),
    (r"\bpending\b", "pending",
     (r"\bcompleted?\b", r"\breceived\b", r"\bcleared\b",
      r"\bresolved\b")),

    # Soft commitments to circle back.
    (r"\bwill (?:follow up|advise|update|keep you (?:posted|updated))\b",
     "will-follow-up",
     (r"\bcompleted?\b", r"\breceived\b", r"\bresolved\b",
      r"\bupdate\b")),
    (r"\b(?:we|i)['’]?ll keep (?:you )?(?:posted|updated)\b",
     "will-update", ()),
    (r"\bwill be (?:closing|closed) on our end\b", "closing-on-our-end",
     (r"\breopen\w*\b", r"\binsured (?:called|reached)\b")),

    # Cost-cap / financial commitments that need reconciliation.
    (r"\btotal cost will not exceed\b", "cost-cap",
     (r"\binvoice\b", r"\bfinal billing\b", r"\breconcil\w+\b")),
)
_COMMITMENT_COMPILED = tuple(
    (re.compile(pat, re.IGNORECASE), label,
     tuple(re.compile(c, re.IGNORECASE) for c in closers))
    for pat, label, closers in _COMMITMENT_PATTERNS
)

# Days of silence after which we consider a commitment "stale" and flag.
DEFAULT_STALE_DAYS = 5

# Authors we treat as "system" rather than a person speaking. Status updates
# and Xactimate auto-summaries don't count toward staleness — silence after
# a system note is meaningless because the system never speaks again.
_SYSTEM_AUTHORS: tuple[str, ...] = (
    "xactnet system", "servpro reviewer",
)


# ── Parsing ────────────────────────────────────────────────────────────────

# Per-note structure (loose):
#   <number>\n
#   <author>\n
#   [<email>\n]              # absent for system authors
#   <franchise-line>\n       # ends with whitespace; e.g. "Servpro of … Ce      "
#   <body…>\n
#   <timestamp>\n            # "Apr 21, 2026 8:16:51 AM"
#   note\n                   # literal kind marker
#
# We split the input on the trailing `note` marker — every line that's
# exactly the word "note" closes a record. The previous timestamp line tells
# us the date; everything between the previous note's closer and the
# timestamp is one note.

_NOTE_TYPE_RE = re.compile(r"^\s*note\s*$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\s*(\d+)\s*$")
_TIMESTAMP_RE = re.compile(
    r"^\s*([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})\s+"
    r"(\d{1,2}):(\d{2}):(\d{2})\s+(AM|PM)\s*$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^\s*<\S+@\S+\.\S+>\s*$")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _parse_timestamp(line: str) -> _dt.datetime | None:
    m = _TIMESTAMP_RE.match(line or "")
    if not m:
        return None
    mon, day, year, hr, mn, sc, ampm = m.groups()
    month = _MONTHS.get(mon.lower())
    if month is None:
        return None
    h = int(hr) % 12
    if ampm.upper() == "PM":
        h += 12
    try:
        return _dt.datetime(int(year), month, int(day),
                            h, int(mn), int(sc))
    except ValueError:
        return None


def parse_xa_notes(raw: str) -> list[dict[str, Any]]:
    """Parse a pasted XA notes panel into structured records (newest first).

    Returns a list of dicts:
        {
          "number": int|None,
          "author": str,
          "email": str,
          "franchise": str,
          "body": str,
          "timestamp": datetime|None,
          "kind": "note" | "status",
          "is_system": bool,
        }

    Resilient to formatting drift: missing email / franchise lines, blank
    sections between notes, ambiguous numbering. Silently drops records we
    can't parse a timestamp for (those are always borderline cases — we'd
    rather under-report than mis-flag).
    """
    if not raw:
        return []
    lines = raw.replace("\r\n", "\n").split("\n")

    # Find all `note` marker line indices — these close records.
    closers = [i for i, ln in enumerate(lines) if _NOTE_TYPE_RE.match(ln)]
    if not closers:
        return []

    notes: list[dict[str, Any]] = []
    prev_close = -1
    for ci in closers:
        block = lines[prev_close + 1:ci]
        prev_close = ci
        # Strip leading/trailing blanks within the block.
        while block and not block[0].strip():
            block.pop(0)
        while block and not block[-1].strip():
            block.pop()
        if not block:
            continue
        # The last non-blank line of the block is the timestamp.
        ts_line = block[-1]
        ts = _parse_timestamp(ts_line)
        if ts is None:
            # Can't trust this block; skip rather than mis-place it.
            continue
        # First line: the note number (digit-only). Optional — pasted
        # excerpts sometimes drop it.
        idx = 0
        num: int | None = None
        if idx < len(block) and _NUMBER_RE.match(block[idx]):
            try:
                num = int(_NUMBER_RE.match(block[idx]).group(1))
            except (ValueError, AttributeError):
                num = None
            idx += 1
        # Next: author. Take the next non-blank line.
        while idx < len(block) and not block[idx].strip():
            idx += 1
        author = block[idx].strip() if idx < len(block) else ""
        idx += 1
        # Optional email line.
        email = ""
        if idx < len(block) and _EMAIL_RE.match(block[idx]):
            email = block[idx].strip().strip("<>")
            idx += 1
        # Optional franchise line. Heuristic: a line with no `@` and ≥ 1
        # word, ending with the timestamp NOT matching. We assume the
        # very next line after author/email is franchise.
        franchise = ""
        if idx < len(block):
            cand = block[idx].strip()
            if cand and not _TIMESTAMP_RE.match(cand):
                franchise = cand
                idx += 1
        # Body: everything between idx and the timestamp line (exclusive).
        body_lines = block[idx:-1]
        body = "\n".join(body_lines).strip()

        author_norm = author.lower().strip()
        is_system = any(sa in author_norm for sa in _SYSTEM_AUTHORS)
        # Detect "Status Update:" body lines from any source as kind=status.
        kind = "status" if (is_system or
                            re.search(r"^status update:", body,
                                      re.IGNORECASE | re.MULTILINE)
                            ) else "note"

        notes.append({
            "number":     num,
            "author":     author,
            "email":      email,
            "franchise":  franchise,
            "body":       body,
            "timestamp":  ts,
            "kind":       kind,
            "is_system":  is_system,
        })
    # Sort newest first (the pasted input is usually already sorted that
    # way, but don't trust it).
    notes.sort(key=lambda n: n["timestamp"] or _dt.datetime.min, reverse=True)
    return notes


# ── Open-commitment detection ──────────────────────────────────────────────

def _detect_commitments(text: str) -> list[dict[str, Any]]:
    """Return every commitment phrase found in `text` along with its
    label and the regex used. Order preserved (matches the iteration
    order of _COMMITMENT_PATTERNS — most-specific first).

    Overlap suppression: if a more-specific phrase ("billing to follow")
    has already matched, the broader generic ("to follow") at the same
    position is skipped — otherwise the same sentence produces two
    redundant flags.
    """
    text = text or ""
    out: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    matched_spans: list[tuple[int, int]] = []
    for regex, label, closers in _COMMITMENT_COMPILED:
        if label in seen_labels:
            continue
        m = regex.search(text)
        if not m:
            continue
        ms, me = m.span()
        if any(s <= ms < e or s < me <= e for s, e in matched_spans):
            continue
        matched_spans.append((ms, me))
        seen_labels.add(label)
        start = max(0, ms - 30)
        end = min(len(text), me + 60)
        snippet = text[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        out.append({
            "label":   label,
            "matched": m.group(0),
            "snippet": snippet,
            "closers": closers,
        })
    return out


def _commitment_was_closed(commitment: dict[str, Any],
                            newer_notes: list[dict[str, Any]]) -> bool:
    """True if any of the commitment's closer regexes match the body of
    a NEWER note. Empty closer tuple → never auto-closed (always flag)."""
    closers: tuple[re.Pattern, ...] = commitment.get("closers") or ()
    if not closers:
        return False
    for n in newer_notes:
        body = n.get("body") or ""
        if not body:
            continue
        for c in closers:
            if c.search(body):
                return True
    return False


def analyze_notes(notes: list[dict[str, Any]], *,
                  stale_days: int = DEFAULT_STALE_DAYS,
                  now: _dt.datetime | None = None
                  ) -> dict[str, Any]:
    """Compute the gap analysis for one job's parsed XA notes.

    Returns a dict:
        {
          "last_human_note":   note dict | None,
          "last_any_note":     note dict | None,
          "days_since_human":  int | None,
          "is_stale":          bool,
          "open_commitments":  [
              {"label", "matched", "snippet", "from_note": <note>},
              …
          ],
          "summary":           "human-readable one-liner for GUI rendering",
        }

    A commitment is "open" when it appears in a note AND no NEWER note
    closes it (per its closer regex set). System / status notes don't
    count toward last_human_note since they're auto-generated.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    notes_sorted = sorted(
        [n for n in notes if n.get("timestamp")],
        key=lambda n: n["timestamp"], reverse=True,
    )
    last_any = notes_sorted[0] if notes_sorted else None
    last_human = next(
        (n for n in notes_sorted if not n.get("is_system")), None)

    days_since_human: int | None = None
    if last_human is not None:
        delta = now - last_human["timestamp"]
        days_since_human = int(delta.total_seconds() // 86400)

    is_stale = (days_since_human is not None
                and days_since_human >= stale_days)

    open_commitments: list[dict[str, Any]] = []
    # Walk notes oldest-first so we can build a "newer notes" list per
    # commitment cheaply.
    chrono = list(reversed(notes_sorted))
    for i, n in enumerate(chrono):
        body = n.get("body") or ""
        if not body or n.get("is_system"):
            continue
        commitments = _detect_commitments(body)
        if not commitments:
            continue
        newer = chrono[i + 1:]
        for c in commitments:
            if _commitment_was_closed(c, newer):
                continue
            open_commitments.append({
                "label":     c["label"],
                "matched":   c["matched"],
                "snippet":   c["snippet"],
                "from_note": n,
            })

    # Dedupe by (label, from_note number) so the same commitment doesn't
    # appear twice if multiple regexes hit overlapping phrases. Keep the
    # most-specific first (already ordered that way in _COMMITMENT_PATTERNS).
    seen: set[tuple[str, int | None]] = set()
    deduped: list[dict[str, Any]] = []
    for c in open_commitments:
        key = (c["label"], c["from_note"].get("number"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    summary_parts: list[str] = []
    if days_since_human is not None:
        summary_parts.append(f"last note {days_since_human}d ago")
    if deduped:
        labels = sorted({c["label"] for c in deduped})
        summary_parts.append(f"open: {', '.join(labels)}")
    if not summary_parts:
        summary_parts.append("no XA notes parsed")

    return {
        "last_human_note":  last_human,
        "last_any_note":    last_any,
        "days_since_human": days_since_human,
        "is_stale":         is_stale,
        "open_commitments": deduped,
        "summary":          " | ".join(summary_parts),
    }


# ── CLI smoke test ─────────────────────────────────────────────────────────

def _cli(argv: list[str]) -> int:
    if not argv:
        print("Usage: python xa_notes.py <path-to-pasted-notes.txt>")
        return 1
    try:
        with open(argv[0], "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        print(f"Could not read {argv[0]}: {e}")
        return 1
    notes = parse_xa_notes(raw)
    print(f"Parsed {len(notes)} notes.")
    for n in notes[:5]:
        ts = n["timestamp"].isoformat() if n["timestamp"] else "?"
        author = n["author"]
        first = (n["body"].split("\n", 1)[0] or "")[:80]
        print(f"  #{n['number']}  {ts}  {author:30s}  {first}")
    if len(notes) > 5:
        print(f"  ... {len(notes) - 5} more")
    print()
    result = analyze_notes(notes)
    print(f"Summary: {result['summary']}")
    print(f"Stale (>={DEFAULT_STALE_DAYS}d): {result['is_stale']}")
    if result["open_commitments"]:
        print(f"Open commitments ({len(result['open_commitments'])}):")
        for c in result["open_commitments"]:
            note = c["from_note"]
            note_ts = (note.get("timestamp") or _dt.datetime.min
                       ).strftime("%Y-%m-%d")
            print(f"  - [{c['label']}]  ({note_ts} #{note.get('number')})  "
                  f"{c['snippet'][:120]}")
    else:
        print("No open commitments detected.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
