"""Put file references on the Windows clipboard.

When the user pastes (Ctrl+V) in XactAnalysis, Outlook, Explorer, or
any other Windows app that accepts files, Windows looks for the
CF_HDROP clipboard format. This module builds the DROPFILES struct
+ writes it to the clipboard so a Python tool can stage "go paste
these files now" in one click.

Falls back to copying the paths as newline-separated plain text if
pywin32 isn't installed — the user can at least paste the list into
a console.
"""
from __future__ import annotations

import os
import struct


def copy_files_to_clipboard(paths) -> dict:
    """Place `paths` (list[str] of absolute file paths) on the
    Windows clipboard as CF_HDROP so the user can Ctrl+V into any
    file-aware Windows app.

    Returns {"ok": bool, "count": int, "via": "hdrop"|"text"|"none",
    "error": str?}.
    """
    clean = [p for p in (paths or []) if p and os.path.isfile(p)]
    if not clean:
        return {"ok": False, "count": 0, "via": "none",
                "error": "no files to copy"}

    # Try the proper CF_HDROP path first — only works on Windows with
    # pywin32 installed. CF_HDROP layout (DROPFILES struct):
    #
    #   DWORD pFiles    — offset to the path list (= sizeof(DROPFILES) = 20)
    #   POINT pt        — drop point (zeroed when not from a drag)
    #   BOOL fNC        — non-client (zeroed)
    #   BOOL fWide      — TRUE when paths are UTF-16
    #
    # followed by the double-null-terminated path list. We use the
    # wide-char path (fWide=1) so non-ASCII filenames survive.
    try:
        import win32clipboard
        import win32con
        # Build the UTF-16LE double-null-terminated path list.
        files_blob = "".join(p + "\0" for p in clean) + "\0"
        files_bytes = files_blob.encode("utf-16-le")
        # DROPFILES header: pFiles=20, pt=(0,0), fNC=0, fWide=1
        header = struct.pack("Iiiii", 20, 0, 0, 0, 1)
        payload = header + files_bytes
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, payload)
        finally:
            try: win32clipboard.CloseClipboard()
            except Exception: pass
        return {"ok": True, "count": len(clean), "via": "hdrop"}
    except Exception as ex_hdrop:
        # Fall back to plain-text path list — less useful but at
        # least the user gets the paths in some form.
        try:
            import subprocess
            txt = "\r\n".join(clean)
            # `clip` (built-in on Windows) reads stdin and copies to
            # clipboard as plain text.
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(txt.encode("utf-16"))
            return {"ok": True, "count": len(clean), "via": "text",
                    "error": f"CF_HDROP failed: {ex_hdrop}"}
        except Exception as ex_text:
            return {"ok": False, "count": len(clean), "via": "none",
                    "error": f"clipboard failed: {ex_hdrop} / {ex_text}"}


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp",
               ".bmp", ".tif", ".tiff", ".gif",
               ".mp4", ".mov", ".m4v", ".avi"}


# ── Temp-folder staging (drag-and-drop into XA) ─────────────────
# CF_HDROP clipboard pastes don't work in XactAnalysis / Xactimate
# — they expect a drag-from-Explorer gesture. So instead of copying
# to clipboard, hardlink (or copy on cross-volume) every selected
# file into a temp folder + open it in Explorer. User drags the
# files into XA, then the folder auto-deletes after `ttl_seconds`.
#
# Hardlinks share disk space + are instant on the same volume; the
# `try/except` falls back to shutil.copy2 when the source is on a
# different drive or the FS doesn't support links.

# Track every staged folder so manual cleanup (eg. on app shutdown)
# can wipe them. Key = path, value = Timer.
_STAGED_FOLDERS: dict = {}


def stage_files_in_temp(paths, *, label: str = "xa_upload",
                        ttl_seconds: int = 60,
                        open_in_explorer: bool = True) -> dict:
    """Drop every file in `paths` into a fresh temp folder + return
    its path. The folder auto-deletes after `ttl_seconds` (default
    1 min). `label` becomes a slug in the folder name so the user
    knows what they're looking at in Explorer.

    Returns {ok, count, folder, ttl_seconds, deletes_at}.
    """
    import os as _os
    import shutil
    import tempfile
    import threading
    import datetime as _dt
    import re as _re

    clean = [p for p in (paths or []) if p and _os.path.isfile(p)]
    if not clean:
        return {"ok": False, "count": 0, "error": "no files to stage"}

    # Sanitize label to keep Explorer happy + add a short timestamp
    # so consecutive stages don't collide.
    slug = _re.sub(r"[^A-Za-z0-9_-]+", "_", (label or "stage")).strip("_")[:48]
    stamp = _dt.datetime.now().strftime("%H%M%S")
    folder = tempfile.mkdtemp(prefix=f"ems_{slug}_{stamp}_")

    # Collision-safe filename — if two source files share a basename
    # (rare with timestamped photos but possible across nested
    # subfolders), append _2, _3, etc.
    used = set()
    def _unique_name(src):
        base = _os.path.basename(src)
        if base not in used:
            used.add(base); return base
        stem, ext = _os.path.splitext(base)
        i = 2
        while f"{stem}_{i}{ext}" in used:
            i += 1
        out = f"{stem}_{i}{ext}"
        used.add(out); return out

    copied = 0
    failed = []
    for src in clean:
        dst = _os.path.join(folder, _unique_name(src))
        try:
            # Hardlink first (instant, same-volume). Fall back to
            # full copy on cross-volume or unsupported FS.
            try:
                _os.link(src, dst)
            except (OSError, NotImplementedError):
                shutil.copy2(src, dst)
            copied += 1
        except Exception as ex:
            failed.append({"path": src, "error": str(ex)})

    if not copied:
        try: shutil.rmtree(folder, ignore_errors=True)
        except Exception: pass
        return {"ok": False, "count": 0,
                "error": "all copies failed",
                "failures": failed}

    # Schedule auto-cleanup. The timer holds a daemon thread so it
    # won't block app shutdown.
    def _cleanup():
        try:
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass
        _STAGED_FOLDERS.pop(folder, None)
    timer = threading.Timer(int(ttl_seconds), _cleanup)
    timer.daemon = True
    timer.start()
    _STAGED_FOLDERS[folder] = timer

    if open_in_explorer:
        try:
            _os.startfile(folder)
        except Exception:
            pass

    deletes_at = (_dt.datetime.now()
                  + _dt.timedelta(seconds=int(ttl_seconds))).strftime("%I:%M:%S %p")
    return {
        "ok":          True,
        "count":       copied,
        "failed_count": len(failed),
        "folder":      folder,
        "ttl_seconds": int(ttl_seconds),
        "deletes_at":  deletes_at,
    }


def cleanup_staged_folders() -> int:
    """Force-delete every still-staged temp folder. Returns count.
    Used on launcher shutdown so we don't leak temp dirs."""
    import shutil
    count = 0
    for folder, timer in list(_STAGED_FOLDERS.items()):
        try: timer.cancel()
        except Exception: pass
        try:
            shutil.rmtree(folder, ignore_errors=True)
            count += 1
        except Exception:
            pass
        _STAGED_FOLDERS.pop(folder, None)
    return count


def list_image_files(folder: str, recursive: bool = True) -> list:
    """Return absolute paths of every image-ish file under `folder`.

    Recursive by default — SERVPRO job folders typically nest by
    tech name or date (PICS/Initial/<Tech>/, PICS/Demo/<Date>/, etc.)
    so a non-recursive walk would return zero for most jobs. Pass
    `recursive=False` to limit to the top-level directory only.

    Skips non-image extensions so a stray .docx or .pdf in a photos
    folder doesn't pollute the paste.
    """
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    if recursive:
        # os.walk handles the "folder within folder" nesting the
        # user is hitting. Sort top-to-bottom so the paste lands in
        # a predictable order (root files first, then nested).
        for dirpath, _dirs, fnames in os.walk(folder):
            for fn in fnames:
                if os.path.splitext(fn)[1].lower() in _IMAGE_EXTS:
                    out.append(os.path.join(dirpath, fn))
    else:
        try:
            with os.scandir(folder) as it:
                for e in it:
                    try:
                        if not e.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    if os.path.splitext(e.name)[1].lower() in _IMAGE_EXTS:
                        out.append(e.path)
        except OSError:
            return []
    out.sort(key=lambda p: os.path.basename(p).lower())
    return out
