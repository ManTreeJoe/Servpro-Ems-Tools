"""SharePoint-enrichment + PICS-resolution logic (UI-free).

Extracted from run_audit_gui.py so the web panels + the audit walk can
resolve PICS folders and diff OneDrive vs SharePoint without importing the
8K-line Tk module. `run_audit_gui` re-exports these names via a shim, so the
Tk UI and external callers are unaffected. See EMS_Tk_Extraction_Plan.md.

Phase 1c slice 2b: PICS/unit resolution helpers + SP-manifest helpers +
`enrich_with_sharepoint`. Multi-unit folder parsing is imported lazily from
multi_unit_gui inside the functions to avoid an import cycle.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time

import paths
import persistence
# Run-doc + stage helpers come from already-extracted UI-free modules.
# No import cycle: run_doc does not import sp_enrich. See
# EMS_Tk_Extraction_Plan.md.
from run_doc import _extract_date_from_folder_name, _find_run_doc_for_date
from stages import detect_sp_folder_subfolder as _detect_stage_subfolder

_PIC_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif",
             ".webp", ".bmp", ".tif", ".tiff", ".gif",
             ".mp4", ".mov", ".m4v", ".avi"}


def _resolve_pics_folder(job_path):
    """Given an audit result's job folder path (e.g. .../<client>), return
    (pics_path, image_count) where pics_path is the canonical PICS folder
    under EMS/ or CONTENTS/. Returns (None, 0) if no PICS dir is found.

    Counts images recursively across all stage subfolders so the user can
    see at a glance whether ANY photos exist for the job, even if the
    specific stage folder they need (e.g. Initial pics) is empty.
    """
    if not job_path or not os.path.isdir(job_path):
        return (None, 0)
    options = _resolve_all_pics_folders(job_path)
    if not options:
        return (None, 0)
    label, pics, _n = options[0]
    # Combined count across every PICS variant — matches old behavior
    # where the badge reflected total photos for the job.
    count = sum(opt[2] for opt in options)
    return (pics, count)


def _resolve_all_pics_folders(job_path):
    """Return every PICS variant present under the job folder, in priority
    order:  EMS/PICS, CONTENTS/PICS, <root>/PICS, plus one entry per
    Unit/Apt subfolder for multi-unit properties.

    Some jobs need photos filed in CONTENTS (e.g. contents-only losses)
    instead of EMS — the audit dialog uses this list to let the user pick
    a destination per copy.

    Older jobs sometimes use "Photos" instead of "PICS"; both names are
    accepted at every position so the SP-import flow finds them either way.

    Multi-unit properties (parent folders with `Unit XXX` / `Apt XXX`
    subfolders — Avila Apartments style) expose each unit's
    `<unit>/EMS/PICS` as its own option so imports can be routed into
    the right unit. The entry's label is "Unit 1017 / EMS / PICS" so
    the destination dropdown is unambiguous.

    Returns a list of (label, path, image_count) tuples; empty list if
    nothing exists.
    """
    if not job_path or not os.path.isdir(job_path):
        return []
    candidates = []
    for parent_label, parent_sub in (("EMS", "EMS"),
                                     ("CONTENTS", "CONTENTS"),
                                     ("", "")):
        for leaf in ("PICS", "Photos"):
            parts = [p for p in (parent_sub, leaf) if p]
            label = " / ".join([s for s in (parent_label, leaf) if s])
            candidates.append((label, os.path.join(job_path, *parts)))

    # Multi-unit: each Unit/Apt folder anywhere under the job (up to
    # 3 levels deep — Action Property Management → Villaigo → Unit 101)
    # gets its own PICS variants appended after the parent's. Label
    # uses the relative path so nested units stay disambiguated.
    # Lazy import avoids a multi_unit_gui → run_audit_gui cycle.
    try:
        from multi_unit_gui import list_unit_subfolders
        unit_subs = list_unit_subfolders(job_path)
    except Exception:
        unit_subs = []
    for u in unit_subs:
        rel = u.get("rel") or u["name"]
        # Convert OS-specific separators to " / " for display so the
        # dropdown reads "Villaigo / Unit 101 / EMS / PICS" on Windows
        # AND a hypothetical *nix run.
        rel_disp = rel.replace(os.sep, " / ").replace("/", " / ")
        for leaf in ("PICS", "Photos"):
            label = f"{rel_disp} / EMS / {leaf}"
            candidates.append(
                (label, os.path.join(u["path"], "EMS", leaf)))

    out = []
    for label, p in candidates:
        if not os.path.isdir(p):
            continue
        n = 0
        try:
            for _dp, _ds, files in os.walk(p):
                for fn in files:
                    if os.path.splitext(fn)[1].lower() in _PIC_EXTS:
                        n += 1
        except OSError:
            pass
        out.append((label, p, n))
    return out


_STAGE_FOLDER_PATTERNS = [
    # (badge label, regex matched against the subfolder name).
    # Order doesn't matter for badge surfacing — we collect all hits.
    # Patterns are deliberately loose: techs name folders all sorts of
    # ways ("Demo pics", "Demo", "DEMO 4-25", "Post Demo") and the
    # audit row should pick them all up.
    ("Initial",     re.compile(r"\binitial\b",            re.IGNORECASE)),
    ("Mold Prep",   re.compile(r"\bmold\s*prep\b",        re.IGNORECASE)),
    ("Post Mold",   re.compile(r"\bpost\s*mold\b",        re.IGNORECASE)),
    ("Demo",        re.compile(r"\bdemo\b",               re.IGNORECASE)),
    ("Post",        re.compile(r"\bpost\b(?!\s*mold)",    re.IGNORECASE)),
    ("Reinspect",   re.compile(r"\breinspect",            re.IGNORECASE)),
    ("Contents",    re.compile(r"\bcontents?\b",          re.IGNORECASE)),
    ("Equipment",   re.compile(r"\b(eq|equipment|drying)\b", re.IGNORECASE)),
    ("Sketch",      re.compile(r"\b(sketch|docusketch)\b", re.IGNORECASE)),
]


def _detect_done_stages(job_path):
    """Walk the job folder's pics/work subfolders and return a list of
    stage labels that appear to have actual work in them.

    The signal is "subfolder name matches a known stage pattern AND
    contains at least one image file" (cheap one-level scandir; we
    don't recurse photo-by-photo just to surface a chip). Used by
    the audit-row renderer to show "Demo · Contents · EQ" so the
    auditor knows what kind of work was done without having to open
    the folder. Returns an ordered de-duped list.
    """
    if not job_path or not os.path.isdir(job_path):
        return []
    found = []
    seen = set()

    def _has_images(folder):
        try:
            with os.scandir(folder) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            ext = os.path.splitext(e.name)[1].lower()
                            if ext in _PIC_EXTS:
                                return True
                        elif e.is_dir(follow_symlinks=False):
                            # One level of recursion handles common
                            # tech-named subfolders like
                            # "Demo pics/Kitchen/IMG_*.jpg".
                            try:
                                with os.scandir(e.path) as inner:
                                    for ee in inner:
                                        try:
                                            if ee.is_file(
                                                    follow_symlinks=False):
                                                ext = os.path.splitext(
                                                    ee.name)[1].lower()
                                                if ext in _PIC_EXTS:
                                                    return True
                                        except OSError:
                                            continue
                            except OSError:
                                continue
                    except OSError:
                        continue
        except OSError:
            return False
        return False

    def _scan_dir(parent):
        if not os.path.isdir(parent):
            return
        try:
            with os.scandir(parent) as it:
                subs = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            return
        for sub in subs:
            for label, pat in _STAGE_FOLDER_PATTERNS:
                if label in seen:
                    continue
                if pat.search(sub.name) and _has_images(sub.path):
                    found.append(label)
                    seen.add(label)
                    break

    # Look in EMS/PICS, CONTENTS/PICS, and the job root — same coverage
    # as `_resolve_all_pics_folders` so we don't miss stages filed
    # under Contents-side trees.
    for parent_sub, leaf in (("EMS", "PICS"), ("EMS", "Photos"),
                              ("CONTENTS", "PICS"), ("CONTENTS", "Photos"),
                              ("", "PICS"), ("", "Photos")):
        parts = [p for p in (parent_sub, leaf) if p]
        _scan_dir(os.path.join(job_path, *parts))

    # CONTENTS at the job root — even when there's no PICS under it,
    # the existence of a non-empty CONTENTS/<anything> tree means
    # there was contents work. Flags it as a chip so the auditor
    # knows to look there.
    contents_root = os.path.join(job_path, "CONTENTS")
    if "Contents" not in seen and os.path.isdir(contents_root):
        try:
            with os.scandir(contents_root) as it:
                if any(True for _ in it):
                    found.append("Contents")
                    seen.add("Contents")
        except OSError:
            pass
    return found


def _unit_segment_from_pics_path(job_path, pics_path):
    """If `pics_path` lives under a Unit/Apt folder ANYWHERE between
    `job_path` and itself, return that folder's full name (e.g.
    'Unit 104-97820- Mendiola, Mary'). None for parent-level PICS
    variants and for paths that don't sit under the job folder.

    Walks every segment of the relative path so nested layouts
    (Action Property Management / Villaigo / Unit 104 / EMS / PICS)
    still resolve to the right unit folder. Returning the FULL name
    (not just the number) lets callers disambiguate when multiple
    units share the same number — Action Property Management →
    Villaigo has three "Unit 104" subfolders with different
    insureds, so unit number alone isn't enough."""
    if not job_path or not pics_path:
        return None
    try:
        rel = os.path.relpath(pics_path, job_path)
    except ValueError:
        return None
    if not rel or rel in (".", ".."):
        return None
    try:
        from multi_unit_gui import _UNIT_FOLDER_RE
    except Exception:
        return None
    for seg in rel.split(os.sep):
        if not seg:
            continue
        if _UNIT_FOLDER_RE.match(seg):
            return seg
    return None


def _unit_num_from_pics_path(job_path, pics_path):
    """Thin wrapper around `_unit_segment_from_pics_path` that returns
    just the unit number (int) — preserved as a separate helper so
    callers that only need the number don't re-parse the segment."""
    seg = _unit_segment_from_pics_path(job_path, pics_path)
    if not seg:
        return None
    try:
        from multi_unit_gui import _UNIT_FOLDER_RE
    except Exception:
        return None
    m = _UNIT_FOLDER_RE.match(seg)
    if not m:
        return None
    try:
        return int(m.group("num"))
    except ValueError:
        return None


# Tokens that should be ignored when scoring insured-name overlap
# between an SP folder name and a unit folder name. These appear in
# nearly every unit-folder name and would inflate matches without
# adding signal.
_UNIT_NAME_STOPWORDS = {
    "unit", "apt", "apartment", "the", "ste", "suite",
    # Common date words that occasionally leak into folder names.
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
}


def _name_tokens_for_unit_match(text):
    """Return lowercase alphabetic tokens (len>=3) suitable for
    insured-name overlap scoring. Drops digits (claim numbers, dates,
    unit numbers) and stopwords so 'Unit 104-97820- Mendiola, Mary'
    contributes {mendiola, mary} — the insured name parts.

    Used by the SP-copy auto-router to pick the right Unit 104 folder
    when multiple share the unit number."""
    if not text:
        return set()
    toks = {t for t in re.findall(r'[a-z]+', text.lower())
            if len(t) >= 3}
    return toks - _UNIT_NAME_STOPWORDS


def _pick_default_pics_path(pics_options):
    """Pick the most likely destination from a list of PICS variants.

    Rule: pick the variant with the most existing photos (it's the one
    techs are actively using). Tie-break by priority — EMS first, then
    CONTENTS, then root PICS — so brand-new jobs with empty PICS still
    land in the conventional spot.

    `pics_options` is a list of dicts ({label, path, count}) already in
    priority order from `_resolve_all_pics_folders`.
    """
    if not pics_options:
        return None
    max_count = max(opt["count"] for opt in pics_options)
    for opt in pics_options:
        if opt["count"] == max_count:
            return opt["path"]
    return pics_options[0]["path"]


# Manifest of SharePoint imports — for each PICS folder we've imported
# into, we track which original SharePoint basenames have already been
# pulled so future audits can suppress them.
#
# Stored under %APPDATA%\Linguar Hub\sp_imports\<hashed-path>.json
# instead of inside the PICS folder itself, so the manifests stay private
# to each PC and never sync into the shared OneDrive.
#
# v2 schema:
#   {"version": 2,
#    "pics_path": "<original absolute pics_path>",  # for debugging
#    "originals": {"img_1234.jpg": <unix_ts_added>, ...}}
#
# v1 fallback: {"originals": ["img_1234.jpg", ...]} — read transparently;
# next append rewrites in v2 form with the current timestamp.
#
# Entries older than _SP_MANIFEST_TTL_DAYS get dropped on every append so
# the file can't grow without bound across months of imports.
_SP_MANIFEST = ".sharepoint_imported.json"   # legacy in-PICS location
_SP_MANIFEST_TTL_DAYS = 90
_SP_MANIFEST_DIR = paths.data("sp_imports")


def _sp_manifest_key(pics_path):
    """Stable, filesystem-safe key for a PICS folder.

    Hash of the normalized absolute path keeps it short + collision-free;
    a readable trailing chunk of the last folder name aids manual debugging
    of the sp_imports/ directory.
    """
    import hashlib
    norm = os.path.normcase(os.path.abspath(pics_path or ""))
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]
    last = os.path.basename(norm.rstrip(os.sep)) or "root"
    safe_last = re.sub(r'[^A-Za-z0-9._-]+', "_", last)[:40]
    return f"{h}__{safe_last}.json"


def _sp_manifest_path(pics_path):
    """Absolute path to this PICS folder's manifest under DATA_DIR."""
    if not pics_path:
        return ""
    return os.path.join(_SP_MANIFEST_DIR, _sp_manifest_key(pics_path))


def _legacy_sp_manifest_path(pics_path):
    """Path the manifest would have lived at before v2 — inside the PICS
    folder. We migrate-on-read and delete the legacy file once it's
    safely under DATA_DIR."""
    if not pics_path:
        return ""
    return os.path.join(pics_path, _SP_MANIFEST)


def _migrate_legacy_sp_manifest(pics_path):
    """Move a leftover in-PICS manifest into DATA_DIR. Best-effort."""
    if not pics_path:
        return
    legacy = _legacy_sp_manifest_path(pics_path)
    if not os.path.isfile(legacy):
        return
    new = _sp_manifest_path(pics_path)
    try:
        os.makedirs(_SP_MANIFEST_DIR, exist_ok=True)
        # Don't clobber a newer DATA_DIR copy if we already migrated.
        if not os.path.exists(new):
            shutil.copy2(legacy, new)
        os.remove(legacy)
    except OSError as ex:
        try:
            import ems_log
            ems_log.warn("run_audit",
                f"legacy sp manifest migration failed for {pics_path!r}: {ex}")
        except Exception:
            pass


def _read_sp_manifest(pics_path):
    """Return the raw manifest dict in v2 form (originals as dict of
    name → timestamp). Reading a v1 file transparently upgrades it in
    memory but does not write back. Empty dict on missing/unreadable.

    Falls back to the legacy in-PICS location and migrates it into
    DATA_DIR on first read so old workspaces upgrade transparently.
    """
    if not pics_path:
        return {}
    _migrate_legacy_sp_manifest(pics_path)
    p = _sp_manifest_path(pics_path)
    if not os.path.isfile(p):
        # Last-ditch: if migration failed (e.g. PICS folder is read-only)
        # still let the user benefit from the legacy manifest's contents.
        legacy = _legacy_sp_manifest_path(pics_path)
        if os.path.isfile(legacy):
            p = legacy
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    originals = data.get("originals")
    now = time.time()
    if isinstance(originals, list):
        # v1 — list of strings; treat all as added "now" so they age out
        # 90 days from this read instead of immediately.
        return {str(o).lower(): now for o in originals if o}
    if isinstance(originals, dict):
        out = {}
        for k, v in originals.items():
            try:
                out[str(k).lower()] = float(v)
            except (TypeError, ValueError):
                out[str(k).lower()] = now
        return out
    return {}


def _read_sp_manifest_originals(pics_path):
    """Return set of lowercase original SP basenames already imported into
    this PICS folder. Old entries (> _SP_MANIFEST_TTL_DAYS days) are
    excluded — they're considered "expired" and can be re-imported if
    the user wants. Empty set on missing/unreadable."""
    data = _read_sp_manifest(pics_path)
    if not data:
        return set()
    cutoff = time.time() - _SP_MANIFEST_TTL_DAYS * 86400
    return {name for name, ts in data.items() if ts >= cutoff}


def _append_sp_manifest_originals(pics_path, new_originals):
    """Add originals to the manifest with a current timestamp; prune any
    entries older than the TTL window so the file can't grow forever."""
    if not pics_path or not new_originals:
        return
    p = _sp_manifest_path(pics_path)
    cur = _read_sp_manifest(pics_path)
    now = time.time()
    cutoff = now - _SP_MANIFEST_TTL_DAYS * 86400
    # Drop expired entries first
    cur = {name: ts for name, ts in cur.items() if ts >= cutoff}
    for o in new_originals:
        if not o:
            continue
        cur[str(o).lower()] = now
    try:
        os.makedirs(_SP_MANIFEST_DIR, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version":   2,
                       "pics_path": os.path.abspath(pics_path),
                       "originals": cur}, f)
        os.replace(tmp, p)
    except OSError as ex:
        # Manifest write failure means the next audit re-flags everything
        # we just imported — log so we have a chance to spot the pattern.
        try:
            import ems_log
            ems_log.warn("run_audit",
                f"sp manifest write failed for {pics_path!r}: {ex}")
        except Exception:
            pass


def _clear_sp_manifest(pics_path):
    """Wipe the SharePoint import manifest for one PICS folder. Used by
    the 'Clear import history' button so the next audit re-evaluates
    every photo from scratch.

    Removes both the new DATA_DIR location and any leftover legacy file
    inside the PICS folder. Returns the count of entries removed (0 if
    no manifest was found)."""
    if not pics_path:
        return 0
    cur = _read_sp_manifest(pics_path)
    for p in (_sp_manifest_path(pics_path),
              _legacy_sp_manifest_path(pics_path)):
        try:
            if p and os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    return len(cur)


def enrich_with_sharepoint(r, run_date, *, folder_index=None,
                           match_cache=None):
    """Walk OneDrive PICS + SharePoint for one audit result and stamp the
    diff stats onto `r` in place. Shared by the bulk audit pass, the
    single-row rescan path, and the snapshot's mini audit (which used to
    skip the SP cross-check entirely).

    Sweep callers should pass `folder_index` (built once via
    sharepoint.build_sharepoint_folder_index()) and a `match_cache` dict
    so the SP folder enumeration / per-folder file walks aren't repeated
    for every client. Single-row callers can omit both.

    Updates: r["pics_options"], r["pics_path"], r["pics_count"],
    r["sharepoint_matches"], r["sharepoint_new"], r["od_diff_stats"].
    No-ops cleanly if the sharepoint module isn't importable (e.g. when
    run from a packaged tool that didn't bundle it)."""
    # Commercial-parent UMBRELLA head is a container, not a job — never
    # scan SharePoint for it (no "N on SP" chip on the head).
    if isinstance(r, dict) and r.get("is_parent"):
        r.setdefault("sharepoint_matches", [])
        r.setdefault("sharepoint_new", 0)
        return
    try:
        from sharepoint import (
            find_sharepoint_folders_for_client,
            list_image_stats_in_tree,
        )
    except Exception:
        return

    # PICS subfolder enumeration (cheap — just lists the EMS/PICS dir,
    # doesn't recurse into images). Always do this so the audit row
    # has its photo count rendered, regardless of whether the SP walks
    # below find anything.
    try:
        job_root = r.get("path")
        all_pics = _resolve_all_pics_folders(job_root)
        if all_pics:
            r["pics_options"] = [
                {"label": lbl, "path": p, "count": n,
                 "unit_num":  _unit_num_from_pics_path(job_root, p),
                 "unit_name": _unit_segment_from_pics_path(job_root, p)}
                for (lbl, p, n) in all_pics]
            r["pics_path"] = all_pics[0][1]
            r["pics_count"] = sum(opt[2] for opt in all_pics)
            # Flag the row as multi-unit when ANY pics option lives under
            # a Unit/Apt subfolder. The audit-card renderer + SP copy
            # dialog use this to switch to per-unit routing UX.
            r["is_multi_unit"] = any(
                opt.get("unit_num") is not None
                for opt in r["pics_options"])
    except Exception:
        pass
    # Done-stages chips — what kind of work has actual photos filed
    # under this job (Demo, Contents, EQ, etc.). The audit row uses
    # this to surface "demo + contents" jobs without making the user
    # open the folder. Cheap-ish (one scandir per stage subfolder)
    # but isolated in a try so a permission error on one job doesn't
    # break the audit pipeline.
    try:
        r["done_stages"] = _detect_done_stages(r.get("path"))
    except Exception:
        r["done_stages"] = []

    try:
        # Tenant names show up on unit jobs and sometimes own the
        # SharePoint folder instead of the property name — pass it as
        # an extra search term so those photos get found. Unit number
        # also flows through so multi-unit properties (Keystone-Highland
        # Village Unit 168 vs Unit 182) don't cross-pollinate matches.
        # Per-client search aliases (set via right-click > Edit aliases
        # or the Job Notes panel) flow through here too — every alias
        # the user registered for this client is offered to the SP
        # matcher as another name to try.
        extra = []
        tenant = r.get("tenant")
        if tenant:
            extra.append(tenant)
        try:
            extra.extend(persistence.get_search_aliases(r["client"]))
        except Exception:
            pass
        matches = find_sharepoint_folders_for_client(
            r["client"], run_date,
            extra_names=extra,
            unit=r.get("unit"),
            folder_index=folder_index,
            match_cache=match_cache) or []
    except Exception:
        matches = []
    rejected = persistence.get_sp_match_rejects(r["client"])
    if rejected:
        matches = [m for m in matches if m.get("path") not in rejected]

    # OD-tree walk only when there are SP folders to diff against.
    # Without matches the size/fingerprint sets are unused, and walking
    # a Files-On-Demand tree can hydrate every placeholder it stats —
    # for a full sweep that turned into hundreds of unnecessary cloud
    # round-trips per skipped job.
    od_names, od_fps = set(), set()
    od_size_counts = {}  # {size: count} so we can require uniqueness
    if matches:
        try:
            # EMS-side only. Earlier code did a whole-job walk that
            # folded in CONTENTS/Photos, so a Contents-team import made
            # EMS audits report "already imported" for photos that never
            # reached EMS/PICS. Walk the pics_options paths instead —
            # those are the canonical PICS roots (EMS/PICS, multi-unit
            # per-unit PICS, root-level PICS) decided by
            # _resolve_all_pics_folders, which already excludes
            # CONTENTS-side trees.
            walk_roots = [opt["path"] for opt in (r.get("pics_options") or [])
                          if os.path.isdir(opt.get("path") or "")]
            for root in walk_roots:
                n, f, c = list_image_stats_in_tree(root)
                od_names |= n
                od_fps   |= f
                for sz, ct in c.items():
                    od_size_counts[sz] = od_size_counts.get(sz, 0) + ct
            for opt in (r.get("pics_options") or []):
                od_names |= _read_sp_manifest_originals(opt["path"])
        except Exception:
            pass

    # Size-alone matching is the loosest fallback (catches files where
    # OD sync rewrote the mtime so the strict (size, mtime) fingerprint
    # broke). It's only safe when the size is UNIQUE in OD — multiple
    # OD photos sharing a size means we can't tell which one (if any)
    # the SP file corresponds to, so a coincidental same-size new SP
    # photo would be silently swallowed as "already in OD". The user
    # hit this when techs added new photos to an SP folder: the strict
    # fingerprint correctly missed them, but the loose size-only check
    # caught a same-size old OD photo and counted them as imported.
    od_unique_sizes = {sz for sz, c in od_size_counts.items() if c == 1}

    new_total = 0
    for m in matches:
        sp_files = m.get("files") or []
        matched_name = matched_fp = matched_size = 0
        new_names = set()
        for nm, fp in sp_files:
            if nm in od_names:
                matched_name += 1
                continue
            # HEIC→JPEG conversion: if the SP file is a .heic and OD
            # has the same stem as a .jpg (from convert_heic_in_dir),
            # treat it as already imported — don't flag as new.
            if nm.lower().endswith(".heic"):
                jpg_nm = nm[:-5] + ".jpg"
                if jpg_nm in od_names:
                    matched_name += 1
                    continue
            if fp is not None:
                if fp in od_fps:
                    matched_fp += 1
                    continue
                if fp[0] in od_unique_sizes:
                    matched_size += 1
                    continue
            new_names.add(nm)
        m["new_count"] = len(new_names)
        m["new_names"] = new_names
        m["match_stats"] = {
            "name":  matched_name,
            "fp":    matched_fp,
            "size":  matched_size,
            "new":   len(new_names),
            "total": len(sp_files),
        }
        new_total += m["new_count"]
        d = _extract_date_from_folder_name(m.get("name", ""))
        if d:
            m["folder_date"] = d.strftime("%m-%d-%Y")
            rd_path = _find_run_doc_for_date(d)
            if rd_path:
                m["run_doc_path"] = rd_path
        m["stage_subfolder"] = _detect_stage_subfolder(m.get("name", ""))

    if matches:
        r["sharepoint_matches"] = matches
        r["sharepoint_new"]     = new_total
    r["od_diff_stats"] = {
        "names": len(od_names),
        "fps":   len(od_fps),
        # Total image-size observations (with duplicates) — what the
        # diagnostic line shows. Unique sizes is what we matched against.
        "sizes": sum(od_size_counts.values()),
        "path":  r.get("path") or "",
    }
