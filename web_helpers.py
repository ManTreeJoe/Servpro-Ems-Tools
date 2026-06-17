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
