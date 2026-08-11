"""SharePoint photo-share utilities.

Single home for the helpers that walk the SharePoint photos share, build
match records for the audit dialog, and diff that share against the
OneDrive PICS tree. Used by both `daily_photos_gui` (the photo-folder
creator + cleanup UI) and `run_audit_gui` (the SharePoint match panel
inside the per-job audit dialog).

These used to live inside `daily_photos_gui.py` and `run_audit_gui` had
to lazy-import them via `from daily_photos_gui import ...` blocks
guarded by ImportError. Pulling them out lets both panels be equal
consumers — neither owns the share logic anymore.
"""
import os
import re

import config
import persistence


# ── Constants ───────────────────────────────────────────────────────────────

# Recognized image / video extensions. Lowercase so callers normalize via
# os.path.splitext(...)[1].lower() before checking. The set is intentionally
# liberal — phones produce HEIC/HEIF, drone footage shows up as MP4/MOV,
# and screenshots come in as PNG.
_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heif",
    ".webp", ".bmp", ".tif", ".tiff", ".gif",
    ".mp4", ".mov", ".m4v", ".avi",
}

# SharePoint photos share root. Resolved LAZILY from config on every access
# (config.load() is mtime-cached, so this is cheap) so a Settings change or
# a department (OC/IE) switch is reflected without restarting the process.
# `sharepoint.PHOTOS_ROOT` still works for callers via the module __getattr__
# below; in-module code calls _photos_root() directly.
def _photos_root():
    # A caller that assigns `sharepoint.PHOTOS_ROOT` directly wins over
    # config. In production nothing does, so this is a no-op — but PEP 562
    # `__getattr__` only fires when normal lookup FAILS, so once a test
    # monkeypatches the documented module constant it lands in globals()
    # and the hook below stops running. Without this check the internal
    # callers would keep reading config and walk the real SharePoint
    # share, which is exactly what made the sharepoint tests fail on a
    # machine that has one mounted.
    override = globals().get("PHOTOS_ROOT")
    if override is not None:
        return override
    return config.load().get("photos_root", "")


def __getattr__(name):
    # PEP 562 module-level attribute hook. Makes `sharepoint.PHOTOS_ROOT`
    # (and function-local `from sharepoint import PHOTOS_ROOT`) resolve
    # fresh each time instead of freezing the import-time value — the key
    # to live department switching.
    if name == "PHOTOS_ROOT":
        return _photos_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _extra_photo_roots():
    """Return a list of additional SharePoint photo roots to scan beyond
    `PHOTOS_ROOT`. Read fresh from config so a Settings-dialog change is
    picked up on the next audit without a restart.

    Used for techs who upload to a sibling SharePoint library instead of
    the standard per-tech subfolder structure (e.g. ServproPhotos /
    Shared Documents). The matcher walks each extra root the same way as
    PHOTOS_ROOT — only folders that already exist on disk are scanned,
    so a stale config entry just no-ops."""
    raw = config.load().get("photos_extra_roots") or []
    if isinstance(raw, str):
        # Tolerate a single-string config entry — the user might paste
        # one path into the field without thinking about list syntax.
        raw = [raw]
    return [str(p).strip() for p in raw if str(p).strip()]


# ── Path utilities ──────────────────────────────────────────────────────────

def _long_path(p):
    r"""Prefix a Windows path with `\\?\` so APIs accept paths longer than
    the legacy 260-char limit. Without this, os.walk silently fails to
    enter deeply nested OneDrive folders like
    `…/EMS/PICS/Initial/ME 4.28.26 Everhome suites Temecula eq/IMG.jpg`,
    which is exactly how the Everhome diff was missing matches.

    No-op on non-Windows. Already-prefixed paths are returned as-is.
    UNC paths get the `\\?\UNC\` form. The prefix changes path parsing
    rules (no `..` expansion, no forward slashes), so callers must hand
    it an already-absolute path.
    """
    if os.name != "nt" or not p:
        return p
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    try:
        ap = os.path.abspath(p)
    except (OSError, ValueError):
        return p
    if ap.startswith("\\\\?\\"):
        return ap
    if ap.startswith("\\\\"):
        return "\\\\?\\UNC\\" + ap[2:]
    return "\\\\?\\" + ap


def _file_fingerprint(p):
    """(size, int(mtime)) — None on stat error. int(mtime) (not float) so
    the same photo round-trips through OneDrive without sub-second sync
    drift treating it as a distinct file."""
    try:
        st = os.stat(_long_path(p))
        return (st.st_size, int(st.st_mtime))
    except OSError:
        return None


def _date_variants(run_date):
    """Return a set of date strings that might appear in a folder name.

    Input: 'MM-DD-YYYY' (e.g. '04-24-2026'). Covers separators (- . /),
    leading-zero vs bare, and 2- vs 4-digit year — techs label folders
    inconsistently (`4/24/26`, `04.24.2026`, `4-24-26`) and we want all
    of them to match.
    """
    try:
        m, d, y = run_date.split("-")
        mi, di, yi = int(m), int(d), int(y)
        y2 = str(yi)[2:]
        variants = set()
        for sep in ("-", ".", "/"):
            for mo in (m, str(mi)):          # "04" and "4"
                for da in (d, str(di)):      # "24" stays "24"; "06" and "6"
                    for yr in (str(yi), y2):  # "2026" and "26"
                        variants.add(f"{mo}{sep}{da}{sep}{yr}")
        return variants
    except Exception:
        return {run_date}


# ── OneDrive PICS tree image-walks (used by the audit's OD-diff) ───────────

def list_image_names_in_tree(path):
    """Recursive walk: return a set of lowercase image basenames under
    `path`. Used to diff OneDrive PICS tree vs a SharePoint folder so
    the audit can flag photos that exist on the share but haven't been
    uploaded to the job folder yet.

    Network walk — call from a background thread.
    """
    out = set()
    if not path or not os.path.isdir(path):
        return out
    try:
        for _root, _dirs, files in os.walk(_long_path(path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in _IMAGE_EXTS:
                    out.add(f.lower())
    except OSError:
        return out
    return out


def list_image_locations_in_tree(path):
    """Recursive walk: return a `{lowercase_basename: folder_path}` map
    of every image under `path`. Used by the SP import flow to find
    the OD subfolder where matching images already live, so a new
    batch can be routed to "the folder that already has the other
    photos from this set" instead of fragmenting the upload into a
    fresh subfolder.

    First-occurrence wins on duplicate basenames — duplicates are rare
    in a job's OD tree and when they happen the first hit is usually
    the original upload location.

    Network walk — call from a background thread.
    """
    out = {}
    if not path or not os.path.isdir(path):
        return out
    try:
        for root, _dirs, files in os.walk(_long_path(path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _IMAGE_EXTS:
                    continue
                k = f.lower()
                if k not in out:
                    # Strip the long-path prefix from the returned
                    # folder so callers can pass it to shutil / os
                    # without surprise (most consumers don't expect
                    # `\\?\` paths). os.walk preserves whatever prefix
                    # we passed in, so root has the prefix.
                    out[k] = _strip_long_prefix(root)
    except OSError:
        return out
    return out


def _strip_long_prefix(p):
    r"""Drop the `\\?\` long-path prefix when present so the path
    round-trips to plain os.path / shutil callers cleanly."""
    if not p:
        return p
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[len("\\\\?\\UNC\\"):]
    if p.startswith("\\\\?\\"):
        return p[len("\\\\?\\"):]
    return p


def list_image_fingerprints_in_tree(path):
    """Recursive walk: return a set of (size, int(mtime)) fingerprints
    for every image under `path`. The diff uses this alongside basenames
    so a photo that's been renamed in OneDrive (e.g. by the SharePoint
    import rename pattern) still matches its SP original by content.

    Network walk — call from a background thread.
    """
    out = set()
    if not path or not os.path.isdir(path):
        return out
    try:
        for root, _dirs, files in os.walk(_long_path(path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _IMAGE_EXTS:
                    continue
                fp = _file_fingerprint(os.path.join(root, f))
                if fp is not None:
                    out.add(fp)
    except OSError:
        return out
    return out


def list_image_sizes_in_tree(path):
    """Recursive walk: return a set of file sizes for images under
    `path`. Loosest match key — used as a third fallback after basename
    and (size, mtime) fingerprint when sync rewrote the mtime so the
    strict fingerprint stops matching.

    NOTE: callers that need to know whether a size is *unique* in the
    OD tree (e.g. to avoid coincidental same-size matches that hide
    genuinely new SP files) should use list_image_size_counts_in_tree
    instead — this returns the deduped set, which can't tell a unique
    size from one that occurs on five different OD photos.

    Network walk — call from a background thread.
    """
    counts = list_image_size_counts_in_tree(path)
    return set(counts.keys())


def list_image_stats_in_tree(path):
    """Single-pass version of list_image_names_in_tree +
    list_image_fingerprints_in_tree + list_image_size_counts_in_tree.
    Returns (names, fingerprints, size_counts).

    The audit's SP enrichment used to call all three back-to-back, which
    meant three full os.walk passes over the same OneDrive-synced tree
    plus duplicate stat() calls per file. With OneDrive Files-On-Demand
    a stat on a placeholder can trigger a cloud hydration, so each
    redundant pass is real wall-clock time on a slow network. One walk,
    one stat per file.

    Network walk — call from a background thread.
    """
    names = set()
    fps = set()
    counts = {}
    if not path or not os.path.isdir(path):
        return names, fps, counts
    try:
        for root, _dirs, files in os.walk(_long_path(path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _IMAGE_EXTS:
                    continue
                names.add(f.lower())
                try:
                    st = os.stat(_long_path(os.path.join(root, f)))
                except OSError:
                    continue
                fps.add((st.st_size, int(st.st_mtime)))
                counts[st.st_size] = counts.get(st.st_size, 0) + 1
    except OSError:
        return names, fps, counts
    return names, fps, counts


def list_image_size_counts_in_tree(path):
    """Like `list_image_sizes_in_tree` but returns a {size: count} dict
    so callers can require uniqueness before treating a size as a
    safe match key. Photos commonly collide on size (same camera,
    same resolution), so when a size occurs on multiple OD files it's
    no longer a reliable identity signal — using it would let new SP
    photos hide behind unrelated old OD photos of the same size.

    Network walk — call from a background thread.
    """
    out = {}
    if not path or not os.path.isdir(path):
        return out
    try:
        for root, _dirs, files in os.walk(_long_path(path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _IMAGE_EXTS:
                    continue
                try:
                    sz = os.path.getsize(os.path.join(root, f))
                except OSError:
                    continue
                out[sz] = out.get(sz, 0) + 1
    except OSError:
        return out
    return out


# ── SharePoint match builder ────────────────────────────────────────────────

def _infer_tech(path):
    """Walk up `path` until its parent is PHOTOS_ROOT — the level at
    which that's true IS the tech folder (Cesar / Mark / Nestor / …).
    Pre-archive structure was `PHOTOS_ROOT/<tech>/<job>` so the
    immediate parent was always the tech. With the monthly archive
    feature jobs now nest as `PHOTOS_ROOT/<tech>/<MonthName YYYY>/
    <job>` — single-step parent lookup would call "April 2026" the
    tech, which is wrong. Walking up handles arbitrary intermediate
    nesting (archive, sub-archives, etc.) without each one needing
    its own special case. Returns "" if the path isn't under
    PHOTOS_ROOT (e.g. extra roots are flat with no tech layer)."""
    _root = _photos_root()
    if not path or not _root:
        return ""
    try:
        root_norm = os.path.normpath(_root)
        cur = os.path.normpath(path)
    except Exception:
        return ""
    while True:
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            return ""
        if os.path.normpath(parent) == root_norm:
            return os.path.basename(cur)
        cur = parent


def _build_sp_match(path, run_date_variants=None, override=False,
                     match_reason=None):
    """Walk one SP folder into a match dict. Used by both the auto-scan
    in find_sharepoint_folders_for_client and the manual-override flow
    so both code paths produce identically-shaped match records.

    `path` should be the absolute path to the SP subfolder. The tech is
    inferred via `_infer_tech` which walks up to the level just below
    PHOTOS_ROOT — robust to the monthly archive's `<tech>/<MonthName
    YYYY>/<job>` nesting. Returns None if the folder doesn't exist or
    has no images. The `override=True` flag flips a marker on the
    dict so the audit dialog can render it differently and offer a
    remove action.

    `match_reason` is a human-readable string explaining why the auto-
    matcher picked this folder (e.g. "last name 'miles' (substring)").
    Surfaced in the audit dialog's per-row "🔍 Why?" button so the user
    can diagnose unexpected hits without spelunking through state.json.
    """
    if not path or not os.path.isdir(path):
        return None
    tech = _infer_tech(path)
    name = os.path.basename(path)
    files = []
    fnames = set()
    try:
        for rt, _ds, fs in os.walk(_long_path(path)):
            for fn in fs:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in _IMAGE_EXTS:
                    continue
                full_p = os.path.join(rt, fn)
                fp = _file_fingerprint(full_p)
                nl_fn = fn.lower()
                fnames.add(nl_fn)
                files.append((nl_fn, fp))
    except OSError:
        return None
    # NOTE: empty folders (no images yet) still count as matches.
    # A folder named `<Tech> <date> <Client>` that exists but hasn't
    # had photos uploaded yet is a meaningful signal — it tells the
    # admin "this tech acknowledged the job; expect photos soon."
    # Previously we returned None here, which silently hid these
    # folders from the audit even when the client/tech/date all
    # matched perfectly. (Guadalupe Arrenquin case 2026-05-18: two
    # Danny folders existed but were empty → audit reported "no SP
    # folders found" → user thought the matcher was broken.)
    nl = name.lower()
    matches_date = bool(run_date_variants) and any(
        d in nl for d in run_date_variants)
    return {
        "tech":          tech,
        "path":          path,
        "name":          name,
        "count":         len(files),
        "matches_date":  matches_date,
        "filenames":     fnames,
        "files":         files,
        "override":      override,
        "match_reason":  match_reason or ("user-pinned override" if override
                                            else "unknown"),
        "empty":         not files,
    }


def _name_search_terms(name):
    """Build (full, last) lowercased lookup terms from a client/tenant
    name. Last-name comes from the comma side ("Smith, John" → "smith")
    or the trailing space token ("John Smith" → "smith"). Returns a
    tuple of (full, last, first) — any may be empty string. `first`
    lets the matcher reject last-name fallback hits when a *different*
    first name appears in the folder (Antonio Garcia bug — bare
    "Garcia, Maria" would otherwise match every Garcia client)."""
    if not name:
        return ("", "", "")
    full = " ".join(name.lower().split())
    if "," in name:
        # "Smith, John" — comma side is last name, post-comma is first.
        last = name.split(",", 1)[0].strip().lower()
        rest = name.split(",", 1)[1].strip().split()
        first = rest[0].lower() if rest else ""
    else:
        parts = name.split()
        last = parts[-1].lower() if parts else ""
        first = parts[0].lower() if len(parts) >= 2 else ""
    return (full, last, first)


# Tokens that look like alphabetic names but are actually job-process
# keywords commonly seen in tech folder names. Used by the last-name
# fallback to skip these when checking for "is there a *different*
# first name in this folder?". Lowercase, no extension/punctuation.
_NON_NAME_FOLDER_TOKENS = frozenset({
    # Job stages
    "initial", "mitigation", "mit", "final", "demo", "mold",
    "extraction", "extract", "dryout", "monitor", "monitoring",
    "moveback", "move", "back", "moveout", "scope", "estimate",
    "estimating", "before", "after", "pre", "post", "reading", "readings",
    "containment", "contents", "pack", "packout", "release",
    "complete", "completed", "finish", "finished", "walkthrough",
    "walk", "rebuild", "recon", "reconstruction", "asbestos",
    "abatement", "te", "mc", "st", "tx", "ml", "eq", "pad",
    "pads", "misc", "photo", "photos", "pic", "pics", "job",
    "jobs", "work", "files", "doc", "docs", "documents",
    # Inspection/visit/service workflow keywords — common in folder
    # names like "Miles post pics 5.1" or "Moore inspection 5.5".
    # Without these the last-name fallback rejects the match because
    # "post"/"inspection" looks like another person's first name.
    "inspection", "inspections", "reinspection", "reinspections",
    "test", "tests", "testing", "tested",
    "service", "call", "calls",
    "appt", "appointment", "appointments",
    "visit", "visits", "checkin", "checkout",
    "emergency", "emerg",
    "report", "reports",
    "approval", "approvals", "approved",
    "follow", "followup", "review",
    # Days
    "mon", "tue", "tues", "wed", "weds", "thu", "thur", "thurs",
    "fri", "sat", "sun",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
    # Months
    "jan", "feb", "mar", "apr", "jun", "jul", "aug",
    "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july",
    "august", "september", "october", "november", "december",
    # Note: "may" omitted — also a common name. Matched dates still
    # filtered by digit-token check anyway.
    # Property/job descriptors
    "house", "home", "apt", "apartment", "unit", "bldg", "building",
    "office", "kitchen", "bath", "bathroom", "bed", "bedroom",
    "garage", "basement", "attic", "living", "dining", "hallway",
    "hall", "room", "ceiling", "floor", "wall", "drywall",
    "carpet", "tile", "wood", "water", "fire", "smoke", "soot",
    "damage", "loss", "claim", "claims", "from", "the", "and", "for",
    "new", "old", "site", "property",
    # Insurance carriers — folder names occasionally include the
    # carrier ("Smith John - State Farm"); without these, the carrier
    # token would be treated as a "different first name" and reject
    # the legitimate match. Listed lowercase, alpha only.
    "insurance", "insurer", "ins", "carrier", "policy", "mutual",
    "auto", "owners", "indemnity",
    "statefarm", "state", "farm", "farmers",
    "allstate", "geico", "progressive", "nationwide",
    "liberty", "travelers", "erie", "hartford", "safeco",
    "foremost", "mercury", "metlife", "country", "encompass",
    "chubb", "cincinnati", "kemper", "amica", "esurance", "usaa",
    "aaa",
})


def _other_first_name_in_folder(folder_lower, our_first, our_last,
                                  *, tech_token=""):
    """Look for an alphabetic 3+ char token in `folder_lower` that
    is NOT our client's first name, NOT their last name, NOT the
    folder's owning tech name, and NOT in `_NON_NAME_FOLDER_TOKENS`.
    Such a token is most likely a different person's first name —
    used to reject last-name fallback matches on folders that
    explicitly belong to a different person.

    `tech_token`: the tech name inferred from the folder's parent
    (e.g. 'Marco' for `Photos/Marco/Marco 05-01-2026 Miguel Alatorre`).
    Without this carve-out the leading 'marco' token gets flagged as
    a foreign first name and the match gets rejected — the bug that
    hid Marco's Alatorre SP folder from the audit.

    Returns the offending token, or None.
    """
    tt = (tech_token or "").strip().lower()
    for tok in re.findall(r'[a-z]+', folder_lower):
        if len(tok) < 3:
            continue
        if tok == our_first or tok == our_last:
            continue
        if tt and tok == tt:
            continue
        if tok in _NON_NAME_FOLDER_TOKENS:
            continue
        return tok
    return None


def _parse_date_in_folder_name(name):
    """Pull a date out of a tech-folder name. Tech naming conventions
    are inconsistent — `4-23-26 Smith`, `Smith 4/23/26`, `4.23.2026
    Smith` — so we look for the first 3-segment numeric run that
    parses as a real date. 2-digit year < 100 → 2000s.
    Returns (year, month) tuple or None."""
    if not name:
        return None
    m = re.search(r'\b(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})\b', name)
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        # Validate by constructing a real date — catches "13/40/2026"
        # type garbage that the regex would happily accept.
        from datetime import datetime as _dt
        _dt(y, mo, d)
    except Exception:
        return None
    return (y, mo)


_MONTH_FOLDER_RE = re.compile(
    # Match any folder whose entire name IS a month — with or without
    # a year. Covers our own canonical "<MonthName YYYY>" archive shells
    # AND bare-month organizational folders some techs already keep
    # (e.g. "March", "March 26"). Either way they're containers, never
    # jobs, so the archiver must skip them.
    r'^(?:january|february|march|april|may|june|july|august|'
    r'september|october|november|december)(?:\s+\d{2,4})?$',
    re.IGNORECASE)


# Tech-level folder names that are NOT actually techs and should be
# excluded from every walk of PHOTOS_ROOT — matching, indexing, the
# archive planner, etc. "Scans" is a shared bucket for scanned paper
# work that has no per-job structure inside it; treating it like a
# tech root surfaces every loose scan as a candidate match. Compared
# case-insensitively. Add more entries here if other shared folders
# show up alongside the techs.
_EXCLUDED_ROOT_FOLDERS = frozenset({"scans"})


def _is_excluded_root_folder(name):
    return (name or "").strip().lower() in _EXCLUDED_ROOT_FOLDERS


def plan_month_archive(year, month):
    """Walk PHOTOS_ROOT (and extra roots) and return a list of folders
    that belong to (year, month) and should be moved into a
    `<MonthName YYYY>` archive folder under their tech.

    Inclusion ladder, in order:
      1. Folder name has a full M-D-Y date — respect it. Include only
         when the name's (year, month) matches the target.
      2. Folder name has a partial M-D (no year) — common shorthand
         like "Smith 4-29". Treat the year as the user's target year
         and include when the month matches.
      3. Folder name has no parseable date at all — fall back to the
         folder's latest file mtime. Include when that timestamp
         falls in (year, month). Catches "FloodAtVersa" / "Smith
         John" type names that techs sometimes use without dating.

    Each entry is a dict:
        {"src": absolute path of the dated folder,
         "dst": where it would land,
         "tech": tech-folder name for grouping in previews,
         "name": original folder name}

    Skips:
      - Month-archive folders themselves (don't archive the archive).
      - Folders whose name encodes a different (year, month) — the
        explicit name wins; mtime fallback only fires for un-dated
        names.
      - Folders already inside an archive folder (depth-2+ matches
        whose tech-relative path goes through a `MonthName YYYY`
        segment).

    Pure / read-only — call from a background thread for the
    network walk. Use `apply_month_archive(plan)` to actually move."""
    from datetime import datetime as _dt
    try:
        month_label = _dt(year, month, 1).strftime("%B %Y")
    except Exception:
        return []

    # Lazy import — avoid pulling audit_logic at module load time.
    try:
        from audit_logic import _latest_mtime
    except Exception:
        _latest_mtime = None

    # 2-segment date pattern (M-D, no year). Used only when the full
    # 3-segment parse misses, so order matters — `_parse_date_in_folder_name`
    # is tried first.
    _PARTIAL_DATE_RE = re.compile(r'\b(\d{1,2})[-./](\d{1,2})\b')

    def _folder_in_target(entry):
        """Return True if this folder belongs in the target (year, month)
        per the rules above. None of the three branches double-counts
        because the first match short-circuits."""
        parsed = _parse_date_in_folder_name(entry.name)
        if parsed is not None:
            return parsed == (year, month)
        # Try partial M-D. Only the FIRST match in the name is used,
        # which matches the 3-segment helper's behavior.
        m2 = _PARTIAL_DATE_RE.search(entry.name)
        if m2:
            pm, pd = int(m2.group(1)), int(m2.group(2))
            try:
                _dt(year, pm, pd)  # validates the day too
                return pm == month
            except Exception:
                pass  # fall through to mtime
        # No date in name — check the folder's latest activity.
        if _latest_mtime is None:
            return False
        try:
            mt = _latest_mtime(entry.path, depth=2)
        except Exception:
            mt = None
        if not mt:
            return False
        try:
            d = _dt.fromtimestamp(mt)
        except (OSError, OverflowError, ValueError):
            return False
        return d.year == year and d.month == month

    plan = []
    seen_dst = set()

    def _scan_tech_root(tech_root):
        try:
            with os.scandir(tech_root) as it:
                entries = list(it)
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            # Skip month archives themselves — don't try to move
            # "April 2026" into "April 2026/April 2026".
            if _MONTH_FOLDER_RE.match(entry.name):
                continue
            if not _folder_in_target(entry):
                continue
            dst_parent = os.path.join(tech_root, month_label)
            dst = os.path.join(dst_parent, entry.name)
            if dst in seen_dst or dst.lower() == entry.path.lower():
                continue
            seen_dst.add(dst)
            plan.append({
                "src":  entry.path,
                "dst":  dst,
                "tech": os.path.basename(tech_root),
                "name": entry.name,
            })

    def _scan_root(root, skip_excluded=True):
        if not root or not os.path.isdir(root):
            return
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    # Skip "Scans" and friends — shared non-tech folders
                    # at the tech level. Only applied to PHOTOS_ROOT (the
                    # tech-layered root); extra roots are flat job lists
                    # and don't have a tech layer to filter on.
                    if skip_excluded and _is_excluded_root_folder(entry.name):
                        continue
                    _scan_tech_root(entry.path)
        except OSError:
            return

    _scan_root(_photos_root(), skip_excluded=True)
    for er in _extra_photo_roots():
        _scan_root(er, skip_excluded=False)

    plan.sort(key=lambda p: (p["tech"].lower(), p["name"].lower()))
    return plan


def apply_month_archive(plan):
    """Execute a plan from `plan_month_archive`. Creates each unique
    destination parent folder, then moves each source into it.
    Returns a dict {"moved": [...], "errors": [(src, str)]}.
    `os.rename` (atomic on the same volume) — if the SP share spans
    a different volume than the local cache, this falls back to a
    copy+delete via shutil.move which can be slower."""
    import shutil
    moved  = []
    errors = []
    for entry in plan:
        src, dst = entry["src"], entry["dst"]
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                errors.append((src, f"destination already exists: {dst}"))
                continue
            shutil.move(src, dst)
            moved.append(entry)
        except Exception as ex:
            errors.append((src, str(ex)))
    return {"moved": moved, "errors": errors}


def build_sharepoint_folder_index():
    """Walk PHOTOS_ROOT (+ extras) once and return a flat list of every
    subfolder path/name up to depth 2. Used by callers that need to match
    many clients in a single pass: instead of re-walking the share for
    each client (the cost dominates a full audit sweep), they pass this
    index to find_sharepoint_folders_for_client and the per-client work
    becomes a name-match filter over an already-collected list.

    Each entry: {"path": str, "name": str, "is_tech_root": bool}.
    `is_tech_root` flags entries that are direct children of a configured
    photos root — those are tech folders (Cesar, Mark, Robert, ...) and
    should NEVER be matched as job folders. A tech named "Robert" would
    otherwise pull every "Robert" client's audit row into the tech's
    own folder. The matcher skips these.

    Network walk — call from a background thread.
    """
    index = []
    seen = set()

    def _walk(path, depth, max_depth=2, has_tech_layer=True):
        if depth > max_depth:
            return
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.path in seen:
                continue
            # Drop tech-layer entries that are excluded shared
            # folders (e.g. "Scans"). Skipping them at depth==0
            # also prunes everything inside, so no Scans content
            # ever lands in the index — which means the matcher
            # and archive planner never see it either.
            if (has_tech_layer and depth == 0
                    and _is_excluded_root_folder(entry.name)):
                continue
            seen.add(entry.path)
            # `has_tech_layer` separates PHOTOS_ROOT (where depth-1
            # entries are techs like Cesar/Mark) from extra roots
            # like ServproPhotos that dump job folders flat at the
            # top level. Only the former gets the tech-root mark.
            # `is_month_archive` flags `<MonthName YYYY>` folders
            # so they aren't mistaken for jobs — without this,
            # a folder like "April 2026" inside a tech root would
            # match a client surnamed "April" via the last-name
            # fallback.
            index.append({"path": entry.path,
                          "name": entry.name,
                          "is_tech_root": (has_tech_layer
                                           and depth == 0),
                          "is_month_archive": bool(
                              _MONTH_FOLDER_RE.match(entry.name))})
            _walk(entry.path, depth + 1, max_depth,
                  has_tech_layer=has_tech_layer)

    _root = _photos_root()
    if _root and os.path.isdir(_root):
        _walk(_root, 0, has_tech_layer=True)
    for er in _extra_photo_roots():
        if er and os.path.isdir(er):
            # Extra roots are typically flat (jobs at depth-1) — don't
            # blanket-skip their depth-1 entries.
            _walk(er, 0, has_tech_layer=False)
    return index


def _folder_is_empty_of_images(path):
    """True when `path` (recursive) contains zero image/video files.
    A folder full of stray .DS_Store / Thumbs.db / .pdf still counts
    as empty for the cleanup purpose — those are bookkeeping
    artifacts, not the photo work the folder was created to hold.

    Stops scanning at the first image found (early exit), so empty
    folders are cheap to confirm and folders with content bail
    quickly rather than walking the whole tree.
    """
    if not path or not os.path.isdir(path):
        return False
    try:
        for _root, _dirs, files in os.walk(_long_path(path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in _IMAGE_EXTS:
                    return False
    except OSError:
        return False
    return True


def find_empty_photo_folders():
    """Walk PHOTOS_ROOT (+ extras) and return every job-level folder
    that contains zero photo/video files. Used by the Photo Folders
    cleanup dialog.

    Returns a list of dicts:
        {"path":     absolute folder path,
         "name":     leaf folder name (e.g. "5-3-26 Smith"),
         "tech":     inferred tech name ("Fernando", "Mark E", …),
         "age_days": days since folder mtime, float,
         "mtime":    POSIX timestamp}

    Tech-root + month-archive entries are excluded — those are
    organizational shells, never job folders. The age field lets the
    UI offer a "older than N days" filter without having to re-stat
    every folder when the threshold changes.

    Network walk — call from a background thread.
    """
    import time as _time
    out = []
    try:
        index = build_sharepoint_folder_index()
    except Exception:
        return out
    # Folder names that look "job-like" but are actually shared
    # organizational buckets — never candidates for cleanup even
    # when they're empty. Includes the tech-level excluded names
    # (Scans) plus a few SharePoint placeholders that appear at
    # nested depths in some shares (Documents, Forms).
    _CLEANUP_EXCLUDE_NAMES = {"scans", "documents", "forms",
                               "shared documents", "site assets"}

    now_ts = _time.time()
    for entry in index:
        if entry.get("is_tech_root") or entry.get("is_month_archive"):
            continue
        name = (entry.get("name") or "").strip().lower()
        if name in _CLEANUP_EXCLUDE_NAMES:
            continue
        path = entry.get("path") or ""
        if not path or not os.path.isdir(path):
            continue
        # Cheap empty-check first — skip the stat() if we already
        # know the folder has photos in it.
        if not _folder_is_empty_of_images(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        age_days = max(0.0, (now_ts - mtime) / 86400.0) if mtime else 0.0
        try:
            tech = _infer_tech(path)
        except Exception:
            tech = ""
        out.append({
            "path":     path,
            "name":     entry.get("name", "") or os.path.basename(path),
            "tech":     tech or "",
            "age_days": age_days,
            "mtime":    mtime,
        })
    # Newest-first — the user usually wants to leave today's empties
    # alone (techs may upload later) and prune older ones.
    out.sort(key=lambda r: -(r["age_days"] or 0))
    return out


def find_sharepoint_folders_for_client(client, run_date=None,
                                        extra_names=None, unit=None,
                                        folder_index=None,
                                        match_cache=None):
    """Walk every tech-root folder under PHOTOS_ROOT (plus any configured
    `photos_extra_roots`) looking for subfolders whose name matches this
    client's job.

    `extra_names` is a list of additional names to match — used for
    tenant names on unit jobs, where photos sometimes get filed under
    the tenant rather than the property name.

    `unit` is the unit number (string) for multi-unit properties. When
    set, the match becomes UNIT/TENANT-specific: a folder qualifies
    only if its name contains the unit number (word-boundary) OR a
    name from `extra_names`. Bare property-name matches are rejected,
    because the same property has multiple units and a property-only
    match would surface Unit 182's photos on Unit 168's audit row.

    Match dicts come back overrides-first, then auto-matches sorted by
    date-match then image count descending. Match dict shape is
    documented on `_build_sp_match`.

    Network walk — call from a background thread.
    """
    if not client:
        return []

    unit_str = str(unit).strip() if unit else ""
    # Tenant/alias terms — used in both unit and non-unit modes.
    extra_terms = []
    for n in (extra_names or []):
        if not n:
            continue
        t = _name_search_terms(n)
        if t not in extra_terms:
            extra_terms.append(t)

    # Property-name terms — only used in NON-unit mode. For unit jobs,
    # the property name alone is too broad (it'd cross-pollinate between
    # units of the same building).
    if unit_str:
        property_terms = []
    else:
        property_terms = [_name_search_terms(client)]

    def _last_name_hits(folder_lower, last):
        """Word-boundary check for last-name fallback. Plain substring
        matched 'miles' inside 'Smiles', 'documiles', 'Family Smiles
        Dental' etc., which is exactly the Bridgette Miles false-positive
        the user reported. Word boundaries (\\b) treat the surname as a
        token, so 'miles' matches 'Miles 4-24-26' but not 'smiles'."""
        if not last or len(last) < 3:
            return False
        return bool(re.search(rf'\b{re.escape(last)}\b', folder_lower))

    def _name_match_reason(folder_name, *, folder_path=""):
        """Return a string explaining WHY this folder matched, or None.

        `folder_path`: when provided, the tech name is inferred from
        the path's parent dir and excluded from the
        `_other_first_name_in_folder` "is there a foreign first name"
        check. Without this, an SP folder named `<Tech> <date> <Client>`
        gets falsely rejected because the leading tech token reads as
        another person's first name. Critical for the Alatorre Miguel
        case (Marco's SP folder name).

        Surfaced via the audit dialog's per-row debug button so the user
        can diagnose surprise matches (e.g. "Bridgette Miles pulling in
        Bed 1 readings") without re-running the matcher manually."""
        nl = folder_name.lower()
        tech_token = ""
        if folder_path:
            try:
                tech_token = (_infer_tech(folder_path) or "").lower()
            except Exception:
                tech_token = ""
        # Unit number — word boundary so "168" doesn't catch "1681".
        if unit_str and re.search(
                rf'\b{re.escape(unit_str.lower())}\b', nl):
            return f"unit '{unit_str}' (word-boundary match)"
        for full, last, first in property_terms:
            if full and full in nl:
                return f"client name '{full}' (substring of folder)"
            # Last-name fallback — word-boundary so 'miles' doesn't
            # catch 'smiles' / 'documiles' / 'Family Smiles Dental'.
            if _last_name_hits(nl, last):
                # Antonio Garcia bug: bare last-name match is too
                # broad when client has a known first name. Reject if
                # the folder contains a *different* first-name-like
                # token — that's almost always someone else's job.
                if first:
                    other = _other_first_name_in_folder(
                        nl, first, last, tech_token=tech_token)
                    if other:
                        return None
                return f"client last name '{last}' (word-boundary match)"
        for full, last, first in extra_terms:
            if full and full in nl:
                return f"tenant/alias '{full}' (substring of folder)"
            if _last_name_hits(nl, last):
                if first:
                    other = _other_first_name_in_folder(
                        nl, first, last, tech_token=tech_token)
                    if other:
                        return None
                return f"tenant/alias last name '{last}' (word-boundary match)"
        return None

    dates = _date_variants(run_date) if run_date else []

    auto_matches = []
    auto_paths = set()

    def _build_with_cache(path, reason):
        """Look up `path` in match_cache (if provided) before walking the
        folder. Within a single sweep we'd otherwise re-scan the same
        folder's files for every client whose name happens to match it."""
        if match_cache is not None and path in match_cache:
            cached = match_cache[path]
            if cached is None:
                return None
            # Clone — match_reason is per-client, files/count are not.
            rec = dict(cached)
            rec["match_reason"] = reason or rec.get("match_reason", "unknown")
            return rec
        rec = _build_sp_match(path, dates, override=False, match_reason=reason)
        if match_cache is not None:
            match_cache[path] = rec
        return rec

    if folder_index is not None:
        # Sweep mode: caller already enumerated every subfolder once and
        # is reusing the list across all clients. Just filter by name.
        for entry in folder_index:
            # Tech folders (direct children of a photos root) never
            # represent a job, so they shouldn't auto-match. Otherwise
            # a tech named "Robert" would surface as a match for every
            # client whose last name is Robert.
            if entry.get("is_tech_root"):
                continue
            # Month-archive folders ("April 2026") are organizational
            # shells, not jobs — skip them too. Their CONTENTS are the
            # actual jobs and get walked separately by the index.
            if entry.get("is_month_archive"):
                continue
            path = entry.get("path")
            name = entry.get("name")
            if not path or not name or path in auto_paths:
                continue
            reason = _name_match_reason(name, folder_path=path)
            if reason is None:
                continue
            rec = _build_with_cache(path, reason)
            if rec is not None:
                auto_matches.append(rec)
                auto_paths.add(path)
    else:
        # Single-client mode: walk the share fresh.
        def _scan(root, max_depth=2, has_tech_layer=True):
            if not root or not os.path.isdir(root):
                return

            def _walk(path, depth):
                if depth > max_depth:
                    return
                try:
                    with os.scandir(path) as it:
                        entries = list(it)
                except OSError:
                    return
                for entry in entries:
                    if not entry.is_dir():
                        continue
                    # PHOTOS_ROOT: depth=0 means we're at a tech
                    # folder (depth-1 in the tree from that root)
                    # — never match the tech name as a job. Extra
                    # roots are flat, so this skip doesn't apply.
                    if has_tech_layer and depth == 0:
                        # Excluded shared roots ("Scans") never
                        # contain jobs — don't even recurse into
                        # them.
                        if _is_excluded_root_folder(entry.name):
                            continue
                        _walk(entry.path, depth + 1)
                        continue
                    # Month-archive folders are organizational
                    # shells — recurse INTO them but never match
                    # their own name (a "April 2026" archive would
                    # otherwise match a client surnamed April).
                    if _MONTH_FOLDER_RE.match(entry.name):
                        _walk(entry.path, depth + 1)
                        continue
                    reason = _name_match_reason(entry.name,
                                                  folder_path=entry.path)
                    if reason is not None:
                        if entry.path in auto_paths:
                            continue
                        rec = _build_with_cache(entry.path, reason)
                        if rec is not None:
                            auto_matches.append(rec)
                            auto_paths.add(entry.path)
                    else:
                        _walk(entry.path, depth + 1)

            _walk(root, 0)

        _scan(_photos_root(), has_tech_layer=True)
        for er in _extra_photo_roots():
            _scan(er, has_tech_layer=False)

    auto_matches.sort(key=lambda r: (-int(r["matches_date"]), -r["count"]))

    # Manual overrides — persisted folder paths the user has pinned to
    # this client. Merge in front of auto-matches so they're visually
    # prioritized in the dialog. If the auto-scan happened to grab the
    # same path, flip its override flag instead of double-counting.
    overrides_out = []
    for path in persistence.get_sp_match_overrides(client):
        if path in auto_paths:
            for rec in auto_matches:
                if rec["path"] == path:
                    rec["override"] = True
                    break
            continue
        rec = _build_sp_match(path, dates, override=True)
        if rec is not None:
            overrides_out.append(rec)

    return overrides_out + auto_matches


# ══ Recent-folder enumeration ════════════════════════════════
# Moved here from sp_recent_audit (a tkinter dialog module) because
# audit_web's SP Recent mode calls _list_recent_sp_folders and was
# loading the whole Tk stack to reach it. Both functions only ever
# used os + datetime + this module's own index/tech helpers.
# sp_recent_audit re-exports them, so the Tk dialog is unaffected.
from datetime import datetime as _dt_datetime  # noqa: E402


def _folder_mtime(path):
    """Return the most recent mtime among the folder itself and its
    immediate file children. Recursing into subfolders would catch
    deeply-nested updates but adds 10× walk cost on a Files-On-Demand
    tree — top-level scan is enough for the "did anything change in
    this job folder lately?" question we're answering."""
    if not path or not os.path.isdir(path):
        return 0.0
    try:
        latest = os.path.getmtime(path)
    except OSError:
        latest = 0.0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        m = e.stat(follow_symlinks=False).st_mtime
                        if m > latest:
                            latest = m
                except OSError:
                    continue
    except OSError:
        pass
    return latest


def _list_recent_sp_folders(start_ts, end_ts):
    """Return a list of {path, name, tech, mtime, age_days} dicts for
    every job-level SP folder modified between the given timestamps
    (inclusive on both ends).

    Tech-root and month-archive entries are excluded — they're
    organizational shells, never jobs. Falls back to an empty list on
    any IO failure rather than blowing up the dialog.
    """
    out = []
    # Unqualified — this function now lives in the module it used to
    # call through, and `sharepoint.` here would be a NameError that the
    # except below would silently turn into "no recent folders".
    try:
        index = build_sharepoint_folder_index()
    except Exception:
        index = []
    now_ts = _dt_datetime.now().timestamp()
    for entry in index:
        if entry.get("is_tech_root") or entry.get("is_month_archive"):
            continue
        path = entry.get("path") or ""
        if not path:
            continue
        mt = _folder_mtime(path)
        if mt < start_ts or mt > end_ts:
            continue
        try:
            tech = _infer_tech(path)
        except Exception:
            tech = ""
        age_days = max(0.0, (now_ts - mt) / 86400.0)
        out.append({
            "path":     path,
            "name":     entry.get("name", ""),
            "tech":     tech,
            "mtime":    mt,
            "age_days": age_days,
        })
    out.sort(key=lambda r: -r["mtime"])
    return out
