"""OneDrive / SharePoint sync-state detection.

Windows OneDrive marks every cloud-only file with the
`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x00400000) attribute — the
dotted-cloud icon you see in Explorer. The file path exists but the
content hasn't been pulled from the cloud yet.

When the audit walks a SharePoint folder while some files are still
cloud-only placeholders, it can't actually read them — so the audit
falsely sees "no photo" or "missing form" for a file that's just
waiting on download.

This module surfaces that state so the UI can warn the user. It does
NOT force the sync (that's a separate, opt-in path) — just inspects
attributes and counts what's still in the cloud.

Public API:
    is_cloud_only(path)           -> bool
    count_cloud_only(folder, *, max_depth=3, skip_names=...)
        -> {"unsynced": N, "total": M, "samples": [...]}
"""
from __future__ import annotations

import os


# Windows file-attribute bits.
#
# Subtlety: under OneDrive Files-On-Demand mode (the default),
# `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x400000) is set on *every*
# managed file — not just cloud-only ones. After a successful pull
# (via `force_pull` or any other read), the content is on disk but
# that attribute stays set forever because the file remains in
# Files-On-Demand management (OneDrive may evict it later to save
# space). So treating it as "cloud-only" produced false-positives
# that never cleared no matter how many times the user clicked 🔄.
#
# `FILE_ATTRIBUTE_OFFLINE` (0x1000) is the reliable signal: "the
# file content is NOT physically on this machine right now." That's
# the one the chip actually wants to gate on.
#
# `RECALL_ON_OPEN` (0x40000) is included for completeness — it's
# OneDrive's older sync mode marker. Modern Files-On-Demand uses
# OFFLINE + RECALL_ON_DATA_ACCESS, but legacy sync clients may use
# RECALL_ON_OPEN on truly cloud-only files. Both clear after pull.
_FILE_ATTRIBUTE_OFFLINE              = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN       = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

_CLOUD_ONLY_MASK = (_FILE_ATTRIBUTE_OFFLINE
                     | _FILE_ATTRIBUTE_RECALL_ON_OPEN)

# Folders we never want to walk into. Mirrors the audit's scope rules
# (see feedback_ems_vs_contents_scope) — Contents/ holds inventory work
# that doesn't belong in the audit's photo/form universe.
_DEFAULT_SKIP_NAMES = {"contents"}

# Hard ceiling on the per-folder sample list so the UI tooltip stays
# readable. Cloud-only files past this still count toward `unsynced`.
_SAMPLE_CAP = 12


def is_cloud_only(path: str) -> bool:
    """True when `path` is a OneDrive placeholder whose content isn't
    on disk yet. False for everything that's normally readable, and
    False on any stat error (the audit's normal error paths handle
    unreachable files — we don't want sync-detection to add a new
    failure mode)."""
    if not path:
        return False
    try:
        s = os.stat(path)
    except OSError:
        return False
    attrs = getattr(s, "st_file_attributes", 0)
    return bool(attrs & _CLOUD_ONLY_MASK)


def count_cloud_only(folder_path: str, *,
                       max_depth: int = 3,
                       skip_names: set[str] | None = None,
                       ) -> dict:
    """Walk `folder_path` up to `max_depth` levels deep and count
    files that are cloud-only placeholders.

    Returns a dict:
        unsynced  : int  — count of files with the cloud-only flag
        total     : int  — every file walked (including synced ones)
        samples   : list[str] — up to `_SAMPLE_CAP` example basenames
                                 of unsynced files (for a tooltip /
                                 warning message)
        scanned   : bool — False when the path isn't a directory at all

    Cheap by design: stat-only, no file reads. A folder with 1000
    fully-synced photos returns in well under a second.
    """
    out = {"unsynced": 0, "total": 0, "samples": [],
            "scanned": False}
    if not folder_path or not os.path.isdir(folder_path):
        return out
    skip = set(_DEFAULT_SKIP_NAMES)
    if skip_names:
        skip |= {n.lower() for n in skip_names}

    root = os.path.abspath(folder_path)
    base_depth = root.count(os.sep)
    out["scanned"] = True

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped subdirs in-place so os.walk doesn't recurse.
        dirnames[:] = [d for d in dirnames if d.lower() not in skip]
        # Depth cap — count separators relative to the root.
        depth = dirpath.count(os.sep) - base_depth
        if depth >= max_depth:
            dirnames.clear()
        for fn in filenames:
            if fn.startswith("."):
                continue
            out["total"] += 1
            full = os.path.join(dirpath, fn)
            if is_cloud_only(full):
                out["unsynced"] += 1
                if len(out["samples"]) < _SAMPLE_CAP:
                    out["samples"].append(fn)
    return out


def summarize(folder_path: str, **kw) -> str:
    """Short human-readable form of `count_cloud_only`. Empty string
    when the folder is fully synced or unreachable — caller can use
    truthiness as 'should I render a warning?'."""
    r = count_cloud_only(folder_path, **kw)
    if not r["scanned"] or r["unsynced"] == 0:
        return ""
    n = r["unsynced"]
    total = r["total"]
    return f"⚠ {n} of {total} files cloud-only (not synced yet)"


def force_pull(folder_path: str, *,
                max_depth: int = 3,
                skip_names: set[str] | None = None,
                progress_cb=None,
                ) -> dict:
    """Trigger OneDrive to download every cloud-only file under
    `folder_path` by opening each one for a 1-byte read. Windows
    transparently fetches the file content on first access; once
    pulled, subsequent reads come from local disk.

    Returns a dict:
        attempted : int  — number of cloud-only files we tried to pull
        pulled    : int  — successful 1-byte reads
        failed    : int  — OSErrors (network blip, permission, file
                            vanished mid-walk)
        elapsed_s : float — wall-clock seconds spent

    SLOW by design — every cloud-only file is a network round-trip.
    Callers should run this off the UI thread (the audit panel
    threads it). `progress_cb(done, total, current_basename)` is
    called per-file when supplied so the UI can show a progress bar.
    """
    import time
    t0 = time.monotonic()
    out = {"attempted": 0, "pulled": 0, "failed": 0, "elapsed_s": 0.0}
    if not folder_path or not os.path.isdir(folder_path):
        return out
    skip = set(_DEFAULT_SKIP_NAMES)
    if skip_names:
        skip |= {n.lower() for n in skip_names}
    root = os.path.abspath(folder_path)
    base_depth = root.count(os.sep)

    # First pass: collect every unsynced path so we can show a real
    # total in progress callbacks (rather than counting up forever).
    targets: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in skip]
        depth = dirpath.count(os.sep) - base_depth
        if depth >= max_depth:
            dirnames.clear()
        for fn in filenames:
            if fn.startswith("."):
                continue
            full = os.path.join(dirpath, fn)
            if is_cloud_only(full):
                targets.append(full)

    total = len(targets)
    for i, path in enumerate(targets, start=1):
        out["attempted"] += 1
        try:
            with open(path, "rb") as f:
                f.read(1)
            out["pulled"] += 1
        except OSError:
            out["failed"] += 1
        if progress_cb is not None:
            try:
                progress_cb(i, total, os.path.basename(path))
            except Exception:
                pass
    out["elapsed_s"] = round(time.monotonic() - t0, 1)
    return out
