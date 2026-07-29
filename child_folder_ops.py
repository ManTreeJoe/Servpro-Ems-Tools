"""Shared helpers for creating/populating multi-unit (and, Phase 2,
multi-claim) child folders and moving files into them safely.

Extracted so Audit, IUQ and Snapshot share ONE implementation of:
  - collision-safe file move (the `move -> copy2+remove` idiom that was
    copy-pasted across audit_web.py / initial_upload_queue.py, where a
    double-failure was silently swallowed and still counted as success),
  - race-safe child-folder reservation (mirrors run_audit_gui.py:3297),
  - replicating an existing sibling unit's empty subfolder skeleton,
  - the one-click "create the missing referenced unit + route the
    in-progress import into it" action.

Pure filesystem logic — no tkinter, no pywebview. Callers own the UI
confirm dialog; this module never prompts.
"""
from __future__ import annotations
import os
import re
import shutil

# The per-unit skeleton the importers assume when there's no sibling to
# copy from (initial_upload_queue.py routes photos to <unit>/EMS/PICS and
# forms to <unit>/EMS/DOCS). Kept minimal on purpose — a real sibling's
# tree (via replicate_sibling_skeleton) is preferred when one exists.
_FALLBACK_SKELETON = (
    os.path.join("EMS", "PICS"),
    os.path.join("EMS", "DOCS"),
)

# Content dirs whose STRUCTURE we recreate but whose innards we don't
# mirror: PICS/PHOTOS/etc. hold per-job room subfolders (Demo, Bed 1…)
# that shouldn't be cloned into a fresh unit. We create the folder itself
# (importers target EMS/PICS, EMS/DOCS) but stop descending there.
_SKELETON_NO_DESCEND = {
    "pics", "photos", "videos", "from sharepoint",
}


def _hydrate_if_cloud_only(src: str) -> None:
    """Force a OneDrive cloud-only placeholder onto local disk before a
    move/copy reads it. No-op for already-local files or when
    sp_sync_state isn't importable. Mirrors audit_web.py:3198-3211."""
    try:
        import sp_sync_state as _sss
    except Exception:
        return
    try:
        if _sss.is_cloud_only(src):
            with open(src, "rb") as fh:
                fh.read(1)
    except Exception:
        # Pull failed — still try the move; copy2's own read may hydrate,
        # or the error surfaces there with a real message.
        pass


def _collision_free(dest_path: str) -> str:
    """Return `dest_path`, or the first ' (N)' suffixed variant that
    doesn't already exist, so a name clash never clobbers."""
    if not os.path.exists(dest_path):
        return dest_path
    d = os.path.dirname(dest_path)
    stem, ext = os.path.splitext(os.path.basename(dest_path))
    n = 2
    while True:
        cand = os.path.join(d, f"{stem} ({n}){ext}")
        if not os.path.exists(cand):
            return cand
        n += 1


def safe_move(src: str, dest_dir: str) -> str | None:
    """Move `src` into `dest_dir`, collision-safe and cloud-aware.

    Returns the final destination path on success, or None on failure
    (BOTH move and the copy2+remove fallback raised). Callers MUST check
    the return value before counting the file as imported — the old
    inline `except OSError: pass` swallowed total failures and reported
    them as successes (audit bug #6).
    """
    if not src or not os.path.isfile(src):
        return None
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return None
    dest = _collision_free(os.path.join(dest_dir, os.path.basename(src)))
    _hydrate_if_cloud_only(src)
    try:
        shutil.move(src, dest)
        return dest
    except OSError:
        # Cross-volume / locked-source fallback: copy then unlink.
        try:
            shutil.copy2(src, dest)
            os.remove(src)
            return dest
        except OSError:
            # Clean up a half-written copy so we don't leave a partial.
            try:
                if os.path.exists(dest) and not os.path.samefile(dest, src):
                    os.remove(dest)
            except OSError:
                pass
            return None


def reserve_child_dir(parent_path: str, name: str) -> str | None:
    """Create `<parent_path>/<name>` on the calling thread, bumping to
    ' (2)', ' (3)' … if it already exists. Returns the reserved path, or
    None if the parent is missing / creation failed. Reserving here (not
    inside a worker thread) makes back-to-back creates race-safe —
    mirrors run_audit_gui.py:3297-3322.
    """
    if not parent_path or not os.path.isdir(parent_path):
        return None
    name = (name or "").strip()
    if not name:
        return None
    target = os.path.join(parent_path, name)
    n = 2
    while os.path.exists(target):
        target = os.path.join(parent_path, f"{name} ({n})")
        n += 1
    try:
        os.makedirs(target, exist_ok=False)
        return target
    except OSError:
        return None


def replicate_sibling_skeleton(new_child_path: str,
                               sibling_path: str | None = None) -> int:
    """Recreate an empty subfolder skeleton inside `new_child_path`.

    When `sibling_path` is an existing unit folder, mirror its directory
    subtree (empty dirs only — no files). Otherwise lay down the minimal
    `_FALLBACK_SKELETON` the importers expect. Returns the number of
    subfolders created.
    """
    if not new_child_path or not os.path.isdir(new_child_path):
        return 0
    made = 0
    if sibling_path and os.path.isdir(sibling_path):
        for root, dirs, _files in os.walk(sibling_path):
            rel = os.path.relpath(root, sibling_path)
            # Create every dir at this level (incl. PICS/DOCS themselves)…
            for d in dirs:
                target = os.path.join(
                    new_child_path, "" if rel == "." else rel, d)
                try:
                    os.makedirs(target, exist_ok=True)
                    made += 1
                except OSError:
                    pass
            # …but don't descend INTO content dirs — their innards are
            # this unit's room subfolders (Demo, Bed 1…), not structure.
            dirs[:] = [d for d in dirs
                       if d.lower() not in _SKELETON_NO_DESCEND]
    if made == 0:
        # No sibling (or nothing copied) — fall back to the minimal tree.
        for rel in _FALLBACK_SKELETON:
            try:
                os.makedirs(os.path.join(new_child_path, rel),
                            exist_ok=True)
                made += 1
            except OSError:
                pass
    return made


_SIBLING_UNIT_RE = re.compile(
    r"^\s*(?P<prefix>unit|apt|apartment|suite|ste)\b(?P<sep>[\s#:_-]*)\d+",
    re.IGNORECASE)


def compose_unit_name(parent_path: str, unit_num,
                      siblings: list | None = None) -> str:
    """Compose a new unit folder name for `unit_num`, matching the
    property's existing sibling style (prefix word + separator casing).

    `siblings` may be a pre-fetched list of {"name": ...} dicts (e.g. from
    multi_unit_gui.list_unit_subfolders); when omitted it's derived from
    an immediate scan of `parent_path`. Falls back to "Unit <num>".
    """
    num = str(unit_num).strip()
    names = []
    if siblings:
        names = [s.get("name", "") for s in siblings if s.get("name")]
    elif parent_path and os.path.isdir(parent_path):
        try:
            with os.scandir(parent_path) as it:
                names = [e.name for e in it if e.is_dir()]
        except OSError:
            names = []
    for nm in names:
        m = _SIBLING_UNIT_RE.match(nm)
        if m:
            prefix = m.group("prefix")
            sep = m.group("sep") or " "
            return f"{prefix}{sep}{num}"
    return f"Unit {num}"


def create_and_route_unit(parent_path: str, unit_name: str,
                          import_files: list | None = None,
                          sibling_path: str | None = None,
                          pics_subpath: str = os.path.join("EMS", "PICS")
                          ) -> dict:
    """Create the missing child unit folder and (optionally) move the
    in-progress import's files into it — the one-click ➕ action.

    Steps: reserve `<parent>/<unit_name>` (race-safe) → replicate a
    sibling's skeleton (or the fallback) → move each file in
    `import_files` into `<child>/<pics_subpath>` via safe_move.

    Returns {"ok", "path", "created", "moved", "failed":[names], "error"}.
    Callers should have already confirmed the (editable) name + file list
    with the user — this does not prompt.
    """
    child = reserve_child_dir(parent_path, unit_name)
    if not child:
        return {"ok": False, "error": "Could not create the unit folder",
                "path": "", "created": 0, "moved": 0, "failed": []}
    created = replicate_sibling_skeleton(child, sibling_path)
    moved = 0
    failed: list[str] = []
    if import_files:
        dest_dir = os.path.join(child, pics_subpath)
        for src in import_files:
            if safe_move(src, dest_dir):
                moved += 1
            else:
                failed.append(os.path.basename(src or ""))
    return {"ok": True, "path": child, "created": created,
            "moved": moved, "failed": failed}
