"""Job-index logic shared by every storage backend.

Pure computation only — no SQL, no HTTP, no database. It lives here so
`ems_db_sqlite` and `ems_db_supabase` cannot drift apart: `canon_key` IS a
job's identity, and two backends disagreeing on it would silently split one
job into two. The same goes for the link normalizers, the department→root
map, and the child classifier.

Anything that touches storage belongs in a backend, not here.
"""
import os
import re

from persistence import _canon_pin_key as _canon_pin_key_persistence

_UNIT_DETECT_PATTERNS = (
    # "Property (Unit 123)" / "Property (#123)" / "Property (123)"
    re.compile(
        r"^(?P<prop>.+?)\s*\(\s*(?:unit\s+|#\s*)?(?P<unit>\d{2,4})\s*\)",
        re.IGNORECASE),
    # "Property Unit 123" or "Property- Unit 123" or "Property -Unit 123"
    re.compile(
        r"^(?P<prop>.+?)\s*[-\s]+unit\s+(?P<unit>\d{2,4})\b",
        re.IGNORECASE),
    # "Property Apt 123"
    re.compile(
        r"^(?P<prop>.+?)\s*[-\s]+(?:apt|apartment|suite|ste)\s+(?P<unit>\d{2,4})\b",
        re.IGNORECASE),
    # "Property #123"
    re.compile(
        r"^(?P<prop>.+?)\s+#\s*(?P<unit>\d{2,4})\b",
        re.IGNORECASE),
    # "Property 1234" — last resort, 3-4 digit unit only to avoid
    # confusing single-family job names that happen to end in a number.
    re.compile(
        r"^(?P<prop>.+?)\s+(?P<unit>\d{3,4})\b"),
)


def detect_property_and_unit(display_name: str) -> tuple[str | None, str | None]:
    """Try to split a job display name into (property, unit).

    Returns (None, None) when the name doesn't look multi-unit. The
    property string preserves the original casing (so `canon_key()`
    can normalize once at the storage layer); the unit is the bare
    digit string.

    Negative guards to avoid false positives on single-family AR-board
    card names:
      • Prop contains a comma → "Last, First" person form, never a
        property name.
      • Unit looks like a YEAR (2000-2099) AND the form was the
        paren-only variant → very likely a "(2025)" job-year tag
        on a person-named card. Real units don't tend to land in
        this exact slot. Hyphen/Unit-prefixed forms ARE allowed to
        match year-shaped numbers because those formats are
        unambiguously multi-unit ("Apt 2025" still means apt 2025).
    """
    s = (display_name or "").strip()
    if not s:
        return None, None
    for pat in _UNIT_DETECT_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        prop = m.group("prop").strip().rstrip("-").rstrip(",").strip()
        unit = m.group("unit").strip()
        if not (prop and unit):
            continue
        if prop.lower() == "unit":
            continue
        if "," in prop:
            # "Hankiewicz, Markus (2024) - State Farm" — person name
            # masquerading as a property. Skip.
            continue
        try:
            unit_int = int(unit)
        except ValueError:
            unit_int = None
        # Only the paren-form and the bare-number-fallback patterns
        # are ambiguous with year tags; reject year-shaped units on
        # those two paths.
        is_paren_or_bare = (pat is _UNIT_DETECT_PATTERNS[0]
                             or pat is _UNIT_DETECT_PATTERNS[-1])
        if (is_paren_or_bare and unit_int is not None
                and 2000 <= unit_int <= 2099):
            continue
        return prop, unit
    return None, None


def canon_key(name: str) -> str:
    """Return the storage key for `name`. Same rule persistence uses for
    pin keys: casefold + collapse whitespace + strip " - Carrier" suffix.
    Shared so a pin written here lines up with one written by another
    tool that consulted `persistence._canon_pin_key` directly."""
    return _canon_pin_key_persistence(name)


# ── Renames ─────────────────────────────────────────────────────────────
#
# A job's name is rarely right on the first day: intake often has only a
# surname or an address, and the full "Last, First - Carrier" arrives once
# the claim details do. `display_name` is overwritten on every upsert, so
# without this the earlier name simply disappears — and with it the answer
# to "what was this job called when I filed those photos?".
#
# Both backends record the change as a `renamed` event and keep the old
# spelling as an alias, so the old name still resolves to the job.

EVENT_RENAMED = "renamed"


def _squash_name(s: str) -> str:
    """Casefold + collapse whitespace. Two names that differ only here are
    the same name typed twice, not a rename."""
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def is_material_rename(old: str, new: str) -> bool:
    """True when `new` is a genuinely different name from `old`.

    Note this is deliberately FINER than `canon_key`: that strips the
    " - Carrier" suffix, so "Smith, John" and "Smith, John - State Farm"
    share a key. Adding the carrier once it is known is exactly the change
    worth recording, so it must count as material here.

    Blank on either side is never a rename — a partial-update upsert that
    omits the name must not read as one.
    """
    if not (old or "").strip() or not (new or "").strip():
        return False
    return _squash_name(old) != _squash_name(new)


LINK_FOLDER = "folder_path"


LINK_TRELLO = "trello_card"


LINK_COMPANYCAM = "companycam_project"


_STRONG_LINK_TYPES = (LINK_FOLDER, LINK_TRELLO, LINK_COMPANYCAM)


def _norm_link(link_type: str, value: str) -> str:
    """Normalize a link value so reverse lookup is stable no matter how the
    caller spelled it. Folder paths → normcase(normpath) (case/slash-
    insensitive on Windows); Trello → the card id/shortlink pulled out of a
    full URL, lowercased; everything else → stripped."""
    v = (value or "").strip()
    if not v:
        return ""
    if link_type == LINK_FOLDER:
        return os.path.normcase(os.path.normpath(v))
    if link_type == LINK_TRELLO:
        m = re.search(r"/c/([A-Za-z0-9]+)", v)      # full card URL
        if m:
            return m.group(1).lower()
        return v.rsplit("/", 1)[-1].strip().lower()  # bare id / shortlink
    return v


_DEPT_ROOTS_CACHE: list | None = None


def invalidate_department_cache() -> None:
    """Drop the cached department→folder-root map. Call on a department
    switch or after editing department paths in Settings."""
    global _DEPT_ROOTS_CACHE
    _DEPT_ROOTS_CACHE = None


def _department_roots() -> list:
    """[(dept_key, normalized_audit_base), ...], longest root first so a
    nested root wins over a parent. Empty when multi-dept is off."""
    global _DEPT_ROOTS_CACHE
    if _DEPT_ROOTS_CACHE is not None:
        return _DEPT_ROOTS_CACHE
    roots = []
    try:
        import config
        if config.is_multi_dept():
            for d in config.list_departments():
                key = d.get("key") or ""
                base = (config.load_for(key).get("audit_base") or "").strip()
                if key and base:
                    roots.append((key, os.path.normcase(os.path.normpath(base))))
    except Exception:
        roots = []
    roots.sort(key=lambda kv: len(kv[1]), reverse=True)
    _DEPT_ROOTS_CACHE = roots
    return roots


def department_for_path(path: str) -> str | None:
    """Which department owns a job folder, by its root. None when the path
    is blank, matches no configured root, or multi-dept is off."""
    p = (path or "").strip()
    if not p:
        return None
    norm = os.path.normcase(os.path.normpath(p))
    for key, root in _department_roots():
        if norm == root or norm.startswith(root + os.sep):
            return key
    return None


def split_department_path(path: str) -> tuple[str | None, str | None]:
    """(department, path relative to that department's root) for a job
    folder, or (None, None) when it sits under no configured root.

    This is what makes a folder link portable between machines. A root is
    either a server share (X:\\IE_Public — same everywhere) or a synced
    SharePoint library, whose LOCAL path contains the syncing user's own
    profile and differs on every machine:

        C:\\Users\\<user>\\Servpro12342\\Servpro-OC - OC-Onedrive
            -> https://servpro12342.sharepoint.com/sites/Servpro-OC2/...

    Storing "OC" + "2026 OC Jobs\\Garvin Ruth" instead of that absolute path
    lets any machine rebuild it against its own sync root.
    """
    p = (path or "").strip()
    if not p:
        return (None, None)
    norm = os.path.normcase(os.path.normpath(p))
    for key, root in _department_roots():
        if norm == root:
            return (key, "")
        if norm.startswith(root + os.sep):
            return (key, norm[len(root) + 1:])
    return (None, None)


def rebase_department_path(department: str, relative: str) -> str | None:
    """Rebuild an absolute folder path from (department, relative) against
    THIS machine's configured root. None when the department isn't
    configured here."""
    dept = (department or "").strip()
    if not dept:
        return None
    for key, root in _department_roots():
        if key == dept:
            rel = (relative or "").strip()
            return os.path.normpath(os.path.join(root, rel)) if rel else root
    return None


CHILD_CLAIM = "claim"


CHILD_UNIT = "unit"


CHILD_SUBJOB = "subjob"


_UNIT_NAME_RE = re.compile(
    r"\b(?:unit|apt|apartment|suite|ste|space|bldg|building|#)\s*"
    r"([A-Za-z]?\d+[A-Za-z\-]*)", re.IGNORECASE)


def classify_child(name: str) -> tuple:
    """(kind, ordinal) for a child folder name.

    '2nd Claim (KItchen)'   → ('claim', 2)
    'Unit 147 - 3.4.26'     → ('unit', None)
    'Coreland Company u121' → ('subjob', None)
    """
    nm = (name or "").strip()
    if not nm:
        return (CHILD_SUBJOB, None)
    try:
        import job_folders
        n = job_folders.claim_ordinal_of(nm)
    except Exception:
        n = None
    if n:
        return (CHILD_CLAIM, n)
    if _UNIT_NAME_RE.search(nm):
        return (CHILD_UNIT, None)
    return (CHILD_SUBJOB, None)


def _now_iso() -> str:
    """UTC, second resolution, no tzinfo — the timestamp format every
    backend stores."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).replace(
        microsecond=0, tzinfo=None).isoformat()
