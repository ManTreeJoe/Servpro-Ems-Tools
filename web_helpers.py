"""Shared helpers for the Pywebview panels.

Used to be duplicated across audit_web / hygiene_web / iuq_web /
snapshot_web / pipeline_web. Consolidate the small utility layer
here so a fix in one place propagates everywhere.

Public:
    pics_from_jobroot(job_root)   -> str
    job_root_from_pics(pics_root) -> str
    jsonify(value)                -> JSON-safe value
    jsonify_datetime(value)       -> str
    run_bg(target, daemon=True)   -> threading.Thread (started)
"""
from __future__ import annotations
import datetime as _dt
import os
import threading


def pics_from_jobroot(job_root: str) -> str:
    """Given a job-folder root (e.g. ``X:\\IE_Public\\2026\\Jones - Acme``),
    return the path to its PICS subfolder. Prefers ``<root>/EMS/PICS``
    (the modern layout), falls back to ``<root>/PICS`` for legacy jobs.

    Returns the EMS/PICS form even when neither exists — the caller is
    expected to ``os.makedirs(..., exist_ok=True)`` if it intends to
    create.
    """
    if not job_root or not os.path.isdir(job_root):
        return ""
    cand = os.path.join(job_root, "EMS", "PICS")
    if os.path.isdir(cand):
        return cand
    cand2 = os.path.join(job_root, "PICS")
    if os.path.isdir(cand2):
        return cand2
    return cand


def contents_pics_from_jobroot(job_root: str) -> str:
    """Like `pics_from_jobroot` but for the CONTENTS side of a job.

    Returns ``<root>/CONTENTS/PICS`` (preferring an existing
    ``CONTENTS/Photos`` when that's what the job uses). Returns the
    ``CONTENTS/PICS`` form even when neither exists so the caller can
    create it. Used by the SP import "Contents side" toggle.
    """
    if not job_root or not os.path.isdir(job_root):
        return ""
    cand = os.path.join(job_root, "CONTENTS", "PICS")
    if os.path.isdir(cand):
        return cand
    cand2 = os.path.join(job_root, "CONTENTS", "Photos")
    if os.path.isdir(cand2):
        return cand2
    return cand


def job_root_from_pics(pics_root: str) -> str:
    """Walk up from a PICS path to find the job folder root. PICS
    lives at ``<job>/EMS/PICS`` or ``<job>/PICS`` (or ``Photos``/
    ``Contents`` equivalents). Strips one or two segments from the
    right depending on which form was resolved."""
    if not pics_root:
        return ""
    d = pics_root
    base = os.path.basename(d).lower()
    if base in ("pics", "photos"):
        d = os.path.dirname(d)
    base = os.path.basename(d).lower()
    if base in ("ems", "contents"):
        d = os.path.dirname(d)
    return d


def jsonify_datetime(val):
    """Coerce a datetime/date into a JSON-friendly ISO string. The
    pywebview bridge can't serialize datetime objects across the JS
    boundary; stringify them at the shaping layer."""
    if val is None:
        return ""
    if isinstance(val, _dt.datetime):
        return val.strftime("%Y-%m-%d %H:%M")
    if isinstance(val, _dt.date):
        return val.strftime("%Y-%m-%d")
    return str(val)


def jsonify(v):
    """Deep-coerce a value into something ``json.dumps`` can handle.
    Recurses into list/tuple/dict; falls back to ``str(v)`` for
    anything else (datetimes, Path, sets, custom objects)."""
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (_dt.datetime, _dt.date)):
        return jsonify_datetime(v)
    if isinstance(v, (list, tuple)):
        return [jsonify(x) for x in v]
    if isinstance(v, dict):
        return {k: jsonify(x) for k, x in v.items()}
    return str(v)


def set_clipboard_text(text) -> bool:
    """Put plain text on the Windows clipboard — the RIGHT way for a
    pywebview app.

    DO NOT use a throwaway ``tkinter.Tk()`` for this. Tk's clipboard uses
    *delayed rendering*: ``clipboard_append`` makes Tk the clipboard OWNER
    but only serves the bytes when another app requests them. After
    ``root.destroy()`` that owner is dead, so the next paste in ANY app
    (Teams / Excel / browser) blocks waiting on a render that never comes
    — Windows hangs it until a timeout. That's the "clipboard freezes
    constantly" bug. The Win32 path below writes the ACTUAL bytes and
    relinquishes ownership cleanly, so there's nothing to hang on.
    """
    s = "" if text is None else str(text)
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(s, win32con.CF_UNICODETEXT)
        finally:
            try:
                win32clipboard.CloseClipboard()  # MUST close or others hang
            except Exception:
                pass
        return True
    except Exception:
        # Fallback: the built-in clip.exe (also writes real bytes, no
        # delayed rendering). UTF-16LE is what clip.exe expects.
        try:
            import subprocess
            subprocess.run(["clip"], input=s.encode("utf-16-le"),
                           check=True, timeout=5)
            return True
        except Exception:
            return False


def run_bg(target, daemon: bool = True) -> threading.Thread:
    """Fire-and-forget background thread. Mirrors the ``threading.Thread(
    target=_bg, daemon=True).start()`` line that every panel repeats."""
    t = threading.Thread(target=target, daemon=daemon)
    t.start()
    return t


def norm_name(s: str) -> str:
    """Canonicalize a client/folder name for token matching: lowercase,
    drop everything that isn't a letter or space, collapse runs of
    whitespace. Use ``norm_tokens`` if you want the set of length-N
    tokens; this helper just returns the cleaned string."""
    import re as _re
    if not s:
        return ""
    s = _re.sub(r"[^a-z ]", " ", s.lower())
    return _re.sub(r"\s+", " ", s).strip()


def norm_tokens(s: str, min_len: int = 2) -> set:
    """Return the set of length-``min_len``+ tokens after ``norm_name``."""
    return {t for t in norm_name(s).split() if len(t) >= min_len}


# Folder words that carry no identity — every job has them, so a folder
# sharing only these with a client name tells us nothing about whose
# folder it is. "2nd Claim" matching "(2nd Claim)" is the exact trap that
# pinned a 2026 Neely job into a 2025 Alvarez folder.
_PIN_STRUCTURAL_TOKENS = {
    "nd", "rd", "th", "st", "claim", "claims", "job", "jobs", "fire",
    "unit", "apt", "suite", "bldg", "building", "second", "third",
    "fourth", "pics", "docs", "photos", "new", "old", "copy", "final",
    "initial", "contents", "demo", "the", "and",
    # Standard job-folder scaffolding. A pin onto one of these is normal
    # — they are exactly the subfolders someone drills into — and none of
    # them says anything about WHOSE job it is.
    "ems", "doc", "document", "documents", "pictures", "images", "img",
    "mitigation", "monitor", "monitoring", "equipment", "eq", "misc",
    "paperwork", "forms", "before", "after", "during", "progress",
}


def _identity_tokens(s: str) -> set:
    """Name tokens with structural folder words removed — what's left is
    what actually identifies a person or business."""
    return {t for t in norm_tokens(s, 2) if t not in _PIN_STRUCTURAL_TOKENS}


def _tokens_akin(a: str, b: str) -> bool:
    """True when two identity tokens are the same name give or take a
    spelling wobble ("neely"/"neeley", "gonzalez"/"gonzales"). Exact match
    first; near-match only for tokens long enough that a high similarity
    ratio isn't coincidence."""
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def _looks_like_address(seg: str) -> bool:
    """True for folders filed as a street address ("10882 Cochran Ave").
    These are legitimately-filed folders that carry no personal name, so
    their words must not be read as evidence of a DIFFERENT client."""
    import re as _re
    return bool(_re.match(r"^\s*\d{2,6}\s+\w", seg or ""))


def _is_year_folder(seg: str) -> bool:
    """True for the year buckets the share is organised by ("2026 Jobs",
    "2025 LA Fire Jobs"). These and everything above them are structure,
    not identity."""
    import re as _re
    return bool(_re.search(r"(?:19|20)\d{2}", seg or ""))


def folder_pin_mismatch(client: str, path: str, depth: int = 12) -> str:
    """Return a human-readable warning when `path` looks like it belongs to
    a DIFFERENT client than `client`, or "" when the pin looks plausible.

    This is a WARNING, not a verdict — legitimately-filed folders can carry
    no name at all (address-only folders, commercial jobs filed under a
    business name), so callers must let the user confirm and proceed rather
    than blocking the pin. It exists to catch the opposite case: a folder
    whose name clearly belongs to somebody else, which is otherwise
    invisible until months of photos have landed in the wrong job.

    Matching walks up from the pinned folder and stops at the year bucket
    ("2026 Jobs"), so neither the year nor the share root above it
    ("x:\\ie_public" — whose own words would match a client named "Public")
    can launder a match.

    It keeps walking past scaffolding folders rather than giving up: a
    pin onto `<client>\\EMS\\PICS\\Initial` is a perfectly normal thing to
    do, and stopping three levels down would never reach the client name
    and would flag it as somebody else's folder. `depth` is only a
    runaway guard — the year bucket is the real stop.
    """
    if not client or not path:
        return ""
    want = _identity_tokens(client)
    if not want:
        return ""

    import os as _os
    segs = [s for s in _os.path.normpath(path).replace("/", _os.sep)
            .split(_os.sep) if s.strip()]
    have = set()
    for seg in reversed(segs[-depth:] if depth else segs):
        if _is_year_folder(seg) or seg.endswith(":"):
            break
        if _looks_like_address(seg):
            continue
        have |= _identity_tokens(seg)
    # A folder chain with no identity tokens at all (address-only, bare
    # "Unit 5") can't be judged — stay quiet rather than cry wolf.
    if not have:
        return ""
    if any(_tokens_akin(w, h) for w in want for h in have):
        return ""
    return (f"That folder looks like it belongs to someone else. "
            f"\u201c{_os.path.basename(_os.path.normpath(path))}\u201d "
            f"shares no name with \u201c{client}\u201d.")
