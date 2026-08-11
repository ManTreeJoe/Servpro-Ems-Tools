"""Shared dialog + zip-discovery helpers for the Workcenter import flow.

Three places in the suite call essentially the same UI sequence:
    1. Show a "confirm <documents|attachments>*.zip is in Downloads" dialog
       with a clickable WC URL link.
    2. Scan Downloads for matching zips (newest first), collapse multi-part
       sets (-part-1-of-3.zip etc.) into single groups.
    3. If multiple groups, show a picker.

Used to live as `_make_workcenter_action` in run_audit_gui.py, again as
`_make_wc_action_snapshot` in snapshot_gui.py, and as inline dialog code
in `_import_wc_for_card` in initial_upload_queue.py. Three near-identical
implementations meant every bug fix had to land in three places — this
module is the single source.

Per-caller logic that did NOT move here:
    • Target folder resolution (PICS variant, stage subfolder, EMS/DOCS
      route, auto-create on miss) — varies by audit context.
    • Post-import side effects (mark resolved, re-walk card, auto-tick
      Trello, snap an Excel row) — varies by tool.

The helpers below cover the visual + discovery surface. Callers stitch
them together with their own target/post-import logic, which preserves
the per-context behavior that differs intentionally.
"""
from __future__ import annotations

import os
import re
import webbrowser

# tkinter + theme are imported INSIDE the three dialog functions below,
# not here. Everything else in this module is pure (zip discovery,
# grouping, extraction, HEIC conversion, room organising) and is called
# by the web panels — audit_web imports this module just for
# find_wc_zips + the filename patterns. At module scope the theme import
# pulls in customtkinter and PIL, which cost ~400ms of startup that a
# web panel never gets any use out of.


# Workcenter export filenames — "documents.zip" / "documents (1).zip" for
# form bundles, "attachments.zip" / "attachments (3).zip" for photo bundles.
# Used by the WC import flow to grab the right zip from Downloads after the
# user clicks the "🔗 WC" import button. Big jobs come down split as
# "attachments-part-1-of-3.zip" etc.; each pattern matches any single part,
# and WC_MULTIPART_RE + group_wc_zips below collapse the parts back into one
# group so the importer extracts all of them together.
WC_DOCUMENTS_RE = re.compile(
    r'^documents(?:\s*\(\d+\)|-part-\d+-of-\d+)?\.zip$', re.IGNORECASE)
WC_ATTACHMENTS_RE = re.compile(
    r'^attachments(?:\s*\(\d+\)|-part-\d+-of-\d+)?\.zip$', re.IGNORECASE)

# Multi-part WC export pattern: "attachments-part-1-of-3.zip".
# The base + total-parts pair forms a group key so all parts extract
# together.
WC_MULTIPART_RE = re.compile(
    r'^(?P<base>.+?)-part-(?P<n>\d+)-of-(?P<m>\d+)\.zip$',
    re.IGNORECASE)


def group_wc_zips(filenames: list[str], downloads_dir: str
                   ) -> list[tuple[str, list[str]]]:
    """Collapse multi-part WC zip sets into single groups.

    Input: filenames already filtered to a WC zip pattern, sorted
    newest-mtime first. Output: list of (label, [absolute_paths])
    tuples in the same newest-first order — multi-part siblings
    collapsed onto the most-recent member's slot. Single zips become
    one-element groups.
    """
    groups: list[tuple[str, list[str]]] = []
    seen_keys: set[tuple[str, str]] = set()
    for fn in filenames:
        m = WC_MULTIPART_RE.match(fn)
        if m:
            key = (m.group("base").lower(), m.group("m"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            siblings = sorted(
                [f for f in filenames
                 if (lambda mm: mm and (mm.group("base").lower(),
                                          mm.group("m")) == key
                     )(WC_MULTIPART_RE.match(f))],
                key=lambda f: int(WC_MULTIPART_RE.match(f).group("n")))
            label = (f"{m.group('base')}-part-*-of-{m.group('m')}.zip "
                     f"({len(siblings)}/{m.group('m')} parts)")
            paths = [os.path.join(downloads_dir, s) for s in siblings]
            groups.append((label, paths))
        else:
            groups.append((fn, [os.path.join(downloads_dir, fn)]))
    return groups


def trash_imported_zips(paths):
    """Send imported zip(s) to the Recycle Bin after a successful
    import. Accepts a single path or a list (for multi-part WC zips).

    Used by every import flow that pulls from the user's Downloads
    folder (WC docs, WC photos, DocuSketch, DocuSign, Initial-Upload
    forms) so Downloads doesn't pile up with already-imported files.
    Uses send2trash so a misclick / wrong-file import is recoverable.

    Silent: failures are swallowed — the import already succeeded and
    a failed cleanup shouldn't surprise the user or block the success
    flow. Gracefully no-ops when send2trash isn't installed.
    """
    if not paths:
        return
    if isinstance(paths, (str, bytes)):
        paths = [paths]
    try:
        from send2trash import send2trash
    except ImportError:
        return
    for p in paths:
        if not p:
            continue
        try:
            import os as _os
            if _os.path.isfile(p):
                send2trash(p)
        except Exception:
            pass


def find_wc_zips(downloads_dir: str, zip_re: re.Pattern
                  ) -> list[tuple[str, list[str]]]:
    """List WC zip groups in `downloads_dir` newest-first.

    Returns the same shape `group_wc_zips` does. Caller decides what to
    do with zero / one / many groups. Errors (unreadable Downloads
    folder) return an empty list rather than raising so the calling
    dialog can show a clean "not found" toast."""
    try:
        names = sorted(
            [f for f in os.listdir(downloads_dir)
             if zip_re.match(f)
             and os.path.isfile(os.path.join(downloads_dir, f))],
            key=lambda f: os.path.getmtime(
                os.path.join(downloads_dir, f)),
            reverse=True)
    except OSError:
        return []
    return group_wc_zips(names, downloads_dir)


def pick_files_from_downloads(parent, *, kind: str = "files"):
    """Open a native file picker rooted at the Downloads folder so the
    user can hand-select one or more files to import (multi-select for
    multi-part zips or loose photo batches). Returns a list of absolute
    paths, or [] on cancel.

    Used by the import dialogs' "📁 Pick a file…" escape hatch for the
    cases the auto-detector misses — a renamed export, a loose file, a
    zip that doesn't match the WC naming pattern."""
    from tkinter import filedialog
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    init_dir = downloads if os.path.isdir(downloads) else None
    paths = filedialog.askopenfilenames(
        parent=parent,
        title=f"Pick {kind} to import from Downloads",
        initialdir=init_dir,
        filetypes=[("Zip / images / docs",
                    "*.zip *.jpg *.jpeg *.png *.heic *.pdf"),
                   ("All files", "*.*")])
    if not paths:
        return []
    return list(paths)


def prompt_for_wc_zip(parent, *, workcenter_url: str = "",
                       label: str = "documents",
                       kind: str = "forms"):
    """Show the "confirm <label>*.zip is in Downloads" modal dialog.

    Returns:
      • False  — user cancelled / closed the dialog.
      • True   — user clicked Import; caller auto-detects the zip.
      • list[str] — user clicked "📁 Pick a file…" and hand-selected
                    one or more files; caller imports exactly these
                    paths (skipping the auto-detector).

    `workcenter_url` renders as a clickable link when set; falls back
    to a plain "(URL not configured)" italic line otherwise. `label`
    + `kind` shape the body copy.

    Pure UI — does not touch the filesystem or trigger any imports
    beyond the optional file-picker. Caller decides what to do with
    the return."""
    import tkinter as tk
    from theme import (
        BG, GREEN, GREEN_DARK, WHITE, TEXT_DARK, TEXT_GRAY,
        SURFACE_2, LINK_FG, NEUTRAL_HOVER,
    )
    dlg = tk.Toplevel(parent)
    dlg.title("Workcenter Import")
    dlg.resizable(False, False)
    try:
        dlg.transient(parent.winfo_toplevel())
    except Exception:
        pass
    dlg.grab_set()

    wf = tk.Frame(dlg, bg=BG, padx=20, pady=16)
    wf.pack()
    tk.Label(wf, text="Download the Workcenter export from:",
             font=("Segoe UI Variable", 10), bg=BG
             ).pack(anchor="w")
    if workcenter_url:
        lnk = tk.Label(wf, text=workcenter_url,
                        font=("Segoe UI Variable", 9, "underline"),
                        bg=BG, fg=LINK_FG, cursor="hand2")
        lnk.pack(anchor="w", pady=(2, 10))
        lnk.bind("<Button-1>",
                  lambda e: webbrowser.open(workcenter_url))
    else:
        tk.Label(wf, text="(Workcenter URL not configured)",
                 font=("Segoe UI Variable", 9, "italic"),
                 bg=BG, fg=TEXT_GRAY
                 ).pack(anchor="w", pady=(2, 10))
    tk.Label(wf,
             text=f"Confirm the {label}*.zip is in your "
                  "Downloads folder, then click Import.\n\n"
                  "Or use “📁 Pick a file…” to choose any file from "
                  "Downloads manually (e.g. a renamed export or a "
                  "loose file the auto-detector misses).",
             font=("Segoe UI Variable", 10), bg=BG,
             wraplength=380, justify="left"
             ).pack(anchor="w", pady=(0, 12))

    result = [False]   # False | True | list[str]
    def _ok():
        result[0] = True
        dlg.destroy()

    def _pick():
        picked = pick_files_from_downloads(dlg, kind=kind)
        if picked:
            result[0] = picked
            dlg.destroy()

    br = tk.Frame(wf, bg=BG)
    br.pack(fill="x")
    tk.Button(br, text="Cancel", font=("Segoe UI Variable", 9),
              bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
              padx=12, pady=4, command=dlg.destroy
              ).pack(side="left")
    tk.Button(br, text="Import",
              font=("Segoe UI Variable", 9, "bold"),
              bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
              relief="flat", padx=12, pady=4, command=_ok
              ).pack(side="right")
    tk.Button(br, text="📁 Pick a file…",
              font=("Segoe UI Variable", 9),
              bg=SURFACE_2, fg=TEXT_DARK,
              activebackground=NEUTRAL_HOVER,
              relief="flat", padx=12, pady=4, command=_pick
              ).pack(side="right", padx=(0, 6))
    dlg.wait_window()
    return result[0]


def convert_heic_in_dir(folder: str, progress_cb=None) -> int:
    """Convert HEIC/HEIF, JFIF **and WEBP** images in `folder` (recursive) to
    JPEG in-place. Returns the number converted. Silently skips files that
    fail (e.g. a corrupt frame) so one bad file doesn't block the rest.

    HEIC/HEIF need `pillow_heif`; JFIF (JPEG data under an odd extension) and
    WEBP (what CompanyCam / browsers often save) convert with plain Pillow —
    so both are normalized even when pillow_heif is missing. Downstream (audit
    photo checks, viewers, snapshot PDFs) then sees a real .jpg instead of a
    file it may not render.

    `progress_cb(done, total)`, when given, is called once with (0, total)
    then after each file (whether it converted or failed, so the count always
    reaches `total`) — lets the web UI show a live "Converting N/M…"
    indicator. A callback that raises is swallowed."""
    try:
        from PIL import Image as _Image
    except ImportError:
        return 0
    # JFIF + WEBP work with plain Pillow; HEIC/HEIF only when pillow_heif is here.
    exts = {".jfif", ".webp"}
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        exts |= {".heic", ".heif"}
    except ImportError:
        pass
    # Collect first so `total` is known up front for progress reporting.
    targets = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if os.path.splitext(name)[1].lower() in exts:
                targets.append(os.path.join(root, name))
    total = len(targets)
    if progress_cb and total:
        try:
            progress_cb(0, total)
        except Exception:
            pass
    converted = 0
    for i, src in enumerate(targets, start=1):
        stem = os.path.splitext(src)[0]
        jpg_path = stem + ".jpg"
        k = 2
        while os.path.exists(jpg_path):        # don't clobber an existing jpg
            jpg_path = f"{stem} ({k}).jpg"
            k += 1
        try:
            with _Image.open(src) as img:
                img.convert("RGB").save(jpg_path, "JPEG", quality=92)
            # Keep the original capture time on the new file.
            try:
                st = os.stat(src)
                os.utime(jpg_path, (st.st_atime, st.st_mtime))
            except OSError:
                pass
            os.remove(src)
            converted += 1
        except Exception:
            pass
        if progress_cb:
            try:
                progress_cb(i, total)
            except Exception:
                pass
    return converted


# Image / video extensions used by the room-organizer. Mirrors
# sharepoint._IMAGE_EXTS so both diff + import surfaces agree on what
# counts as a photo.
_ROOM_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".webp", ".bmp", ".tif", ".tiff", ".gif",
    ".mp4", ".mov", ".m4v", ".avi",
}

# Stage / qualifier words that separate the room name from the photo
# sequence number in a WC filename ("bed 1 pre 6.jpg" → room "bed 1").
# Everything before the first stage word is the room.
_ROOM_STAGE_WORDS = re.compile(
    r'\b(pre|post|during|mid|after|before|final|demo|mold|'
    r'initial|wet|dry|damage|moisture|equip(?:ment)?|eq|complete)\b',
    re.IGNORECASE)


def room_from_filename(name: str):
    """Derive a room/area name from a WC photo filename, or None when
    the name doesn't follow a room pattern.

    WC room photos look like "bed 1 pre 6.jpg", "bath 2 post 3.jpg",
    "entry pre  8.jpg", "kit pre 3.jpg", "eq 2.jpg". The room is the
    text before the first stage word (pre/post/…); when there's no
    stage word, the trailing photo number is stripped instead
    ("eq 2" → "Eq"). Returns a title-cased room name suitable for a
    subfolder, or None for names that don't look like room photos
    (camera dumps: IMG_0001.jpg, 20260603_164911_iOS.jpg)."""
    stem = os.path.splitext(name or "")[0]
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        return None
    m = _ROOM_STAGE_WORDS.search(stem)
    if m and m.start() > 0:
        room = stem[:m.start()].strip()
    elif m and m.start() == 0:
        # Stage word IS the leading token (e.g. "eq 2", "equipment 5").
        room = m.group(0).strip()
    else:
        # No stage word — strip a trailing " <number>" photo counter.
        room = re.sub(r"\s*\d+\s*$", "", stem).strip()
    room = room.strip(" -_")
    if not room:
        return None
    # Must start with a letter and stay short — rejects timestamp /
    # camera-dump names that don't carry a real room label.
    if not room[0].isalpha():
        return None
    if len(room) > 25:
        return None
    # Reject long digit runs (timestamps embedded mid-name).
    if re.search(r"\d{4,}", room):
        return None
    return room.title()


def organize_by_room(folder: str, *, min_files: int = 4,
                      min_fraction: float = 0.5) -> int:
    """Move top-level image files in `folder` into per-room subfolders
    based on their filenames. No-op (returns 0) when the batch doesn't
    look room-organized.

    Guards so a non-room batch (camera dumps, single-room jobs) is left
    flat:
      • at least `min_files` images at the top level
      • at least `min_fraction` of them resolve to a room name
      • at least 2 distinct rooms (1 room = nothing to separate)

    Files already inside subfolders are left untouched. Collision-safe:
    a name clash inside a room folder gets a " (2)" suffix."""
    try:
        with os.scandir(folder) as _sd:
            entries = [e for e in _sd if e.is_file()]
    except OSError:
        return 0
    images = [e for e in entries
              if os.path.splitext(e.name)[1].lower() in _ROOM_IMAGE_EXTS]
    if len(images) < min_files:
        return 0
    room_of = {}
    for e in images:
        room = room_from_filename(e.name)
        if room:
            room_of[e.name] = room
    if len(room_of) < len(images) * min_fraction:
        return 0
    if len(set(room_of.values())) < 2:
        return 0
    moved = 0
    for e in images:
        room = room_of.get(e.name)
        if not room:
            continue  # leave un-roomable files at the root
        sub = os.path.join(folder, room)
        try:
            os.makedirs(sub, exist_ok=True)
        except OSError:
            continue
        stem, ext = os.path.splitext(e.name)
        dst = os.path.join(sub, e.name)
        k = 2
        while os.path.exists(dst):
            dst = os.path.join(sub, f"{stem} ({k}){ext}")
            k += 1
        try:
            os.replace(e.path, dst)
            moved += 1
        except OSError:
            pass
    return moved


def place_import_paths(paths: list[str], target_dir: str) -> int:
    """Place each path into `target_dir`: zips are extracted, loose
    files (images, PDFs, anything non-zip) are copied straight in.
    Returns the count of items placed. Collision-safe — a loose-file
    name clash gets a " (N)" suffix instead of overwriting.

    Lets the import flow accept BOTH the usual WC zip exports AND any
    hand-picked loose file the user chose via "📁 Pick a file…"."""
    import zipfile
    import shutil
    os.makedirs(target_dir, exist_ok=True)
    placed = 0
    for p in paths:
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p, "r") as z:
                z.extractall(target_dir)
            placed += 1
        else:
            base = os.path.basename(p)
            stem, ext = os.path.splitext(base)
            dst = os.path.join(target_dir, base)
            k = 2
            while os.path.exists(dst):
                dst = os.path.join(target_dir, f"{stem} ({k}){ext}")
                k += 1
            try:
                shutil.copy2(p, dst)
                placed += 1
            except OSError:
                pass
    return placed


def extract_zip_group(chosen_paths: list[str], target_dir: str,
                       *, organize_rooms: bool = False) -> None:
    """Extract every zip in `chosen_paths` into `target_dir`,
    auto-convert any HEIC photos to JPEG, and (when `organize_rooms`)
    sort the extracted photos into per-room subfolders.  Multi-part
    sets pass all member paths; single zips pass a 1-element list.
    Raises the underlying exception so callers can show error toasts.

    Mirrors the inline loop that lived in all three WC-import callers
    pre-consolidation (audit / snapshot / IUQ). The target directory
    is the caller's responsibility (per-context: EMS/DOCS, EMS/PICS/
    Initial, stage subfolder, etc.) since target resolution varies
    too much to lift cleanly here."""
    import zipfile
    import os as _os
    _os.makedirs(target_dir, exist_ok=True)
    for zp in chosen_paths:
        with zipfile.ZipFile(zp, "r") as z:
            z.extractall(target_dir)
    convert_heic_in_dir(target_dir)
    if organize_rooms:
        try:
            organize_by_room(target_dir)
        except Exception:
            pass


def find_sticky_home(chosen_paths, od_pics_root, *,
                       min_matches: int = 2):
    """Detect the OD subfolder where this WC batch should land.

    Mirrors the SP-import sticky-home heuristic: if ≥`min_matches`
    images inside the WC zip(s) already exist somewhere under
    `od_pics_root`, return the OD subfolder that hosts the most of
    them. New files from this batch should go to that same folder so
    related photos stay together instead of fragmenting into a fresh
    stage subfolder.

    Reads zip contents via `zipfile.namelist` (no extraction — cheap
    even for large archives). Walks the OD PICS tree once via
    `sharepoint.list_image_locations_in_tree`. Returns None when the
    inputs are missing, no images match, or no folder reaches the
    `min_matches` threshold (e.g., 1 coincidental filename collision
    isn't strong enough signal).
    """
    if not chosen_paths or not od_pics_root:
        return None
    if not os.path.isdir(od_pics_root):
        return None
    try:
        from sharepoint import _IMAGE_EXTS, list_image_locations_in_tree
    except Exception:
        return None
    import zipfile
    staged = set()
    for zp in chosen_paths:
        try:
            with zipfile.ZipFile(zp, "r") as z:
                for name in z.namelist():
                    base = os.path.basename(name)
                    if not base:
                        continue
                    ext = os.path.splitext(base)[1].lower()
                    if ext in _IMAGE_EXTS:
                        staged.add(base.lower())
        except Exception:
            continue
    if not staged:
        return None
    try:
        od_map = list_image_locations_in_tree(od_pics_root)
    except Exception:
        return None
    if not od_map:
        return None
    from collections import Counter as _Counter
    matches = [od_map.get(nm) for nm in staged if od_map.get(nm)]
    counts = _Counter(m for m in matches if m)
    if not counts:
        return None
    best_folder, best_count = counts.most_common(1)[0]
    if best_count >= int(min_matches) and best_folder:
        return best_folder
    return None


def pick_zip_group(parent, groups: list[tuple[str, list[str]]],
                    *, label: str = "documents"
                    ) -> tuple[str, list[str]] | None:
    """Show a radio-button picker when `groups` has more than one
    entry. Returns the selected (label, [paths]) tuple, or None on
    cancel. Single-element / empty inputs are handled by the caller
    (don't call this with len ≤ 1 — wastes a modal)."""
    if not groups:
        return None
    if len(groups) == 1:
        return groups[0]

    import tkinter as tk
    from theme import BG, GREEN, GREEN_DARK, WHITE, TEXT_DARK, SURFACE_2
    pick_dlg = tk.Toplevel(parent)
    pick_dlg.title(f"Select {label} zip")
    pick_dlg.resizable(False, False)
    try:
        pick_dlg.transient(parent.winfo_toplevel())
    except Exception:
        pass
    pick_dlg.grab_set()

    f = tk.Frame(pick_dlg, bg=BG, padx=16, pady=14)
    f.pack()
    tk.Label(f, text="Multiple exports found — pick one:",
             font=("Segoe UI Variable", 10, "bold"), bg=BG
             ).pack(anchor="w", pady=(0, 8))
    pick_var = tk.IntVar(value=0)
    for idx, (lab, _paths) in enumerate(groups[:6]):
        tk.Radiobutton(f, text=lab, variable=pick_var, value=idx,
                        font=("Segoe UI Variable", 8),
                        bg=BG, activebackground=BG
                        ).pack(anchor="w", pady=2)
    picked = [None]

    def _pick():
        picked[0] = pick_var.get()
        pick_dlg.destroy()

    tk.Button(f, text="Import",
              font=("Segoe UI Variable", 10, "bold"),
              bg=GREEN, fg=WHITE, relief="flat",
              padx=12, pady=4, command=_pick
              ).pack(pady=(12, 0), fill="x")
    pick_dlg.wait_window()
    if picked[0] is None:
        return None
    return groups[picked[0]]
