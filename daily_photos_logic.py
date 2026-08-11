"""Photo-folder resolution and creation — the pure half of daily photos.

`photo_folders_web` needs exactly two things from the daily-photos
feature: work out whether a tech's folder for a job already exists, and
create the ones that don't. Both lived in `daily_photos_gui`, which
imports tkinter, customtkinter and PIL at module scope — so a panel that
only ever renders HTML paid ~800ms and dragged the whole Tk stack in
behind it.

Nothing here touches a widget. It reads SharePoint, matches names, and
makes directories.

⚠ TECH_INITIALS_REVERSE is looked up THROUGH the module, not
from-imported. `audit_logic` REBINDS that name when the tech roster
changes (`global TECH_INITIALS_REVERSE; TECH_INITIALS_REVERSE = {...}`),
so a `from audit_logic import TECH_INITIALS_REVERSE` captured at import
time keeps pointing at the pre-reload dict and files photos under stale
initials. daily_photos_gui still has that from-import.
"""
import os
import re

import config
import sharepoint
from sharepoint import _date_variants  # noqa: F401 — used by _photo_folder_path

# A date inside a SharePoint folder name — "Smith 5-22-26 Demo".
_SP_DATE_RE = re.compile(r'\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}')


def _tech_initials():
    """The live {name: initials} map, fetched per call — the roster
    reload rebinds it, so a cached reference goes stale."""
    try:
        import audit_logic
        return getattr(audit_logic, "TECH_INITIALS_REVERSE", {}) or {}
    except Exception:
        return {}


def _client_match_tokens(client):
    """Build the list of name tokens to scan folder names for.

    Run docs and SharePoint folders use a mix of name conventions:
      - "Smith, John"  → folder usually "Smith ..." → match on "smith"
      - "John Smith"   → folder usually "Smith ..." too → match on "smith"
                          BUT some folders use "John Smith" → match on "john"
      - "Costco"       → single token → match on "costco"
      - "Acme Property Management" → folder could use any word

    Returns lowercased tokens (≥3 chars) plus the bare first token, so
    the fuzzy match has multiple chances to land. Dropped tokens shorter
    than 3 chars to avoid false-pos matches on e.g. "of" / "&".
    """
    parts = [p.strip() for p in client.split(",")]
    candidates = []
    if len(parts) > 1:
        # "Smith, John" form — surname is before the comma.
        surname = parts[0].split()[0] if parts[0].split() else ""
        if surname:
            candidates.append(surname.lower())
        givens = parts[1].split() if len(parts) > 1 else []
        if givens:
            candidates.append(givens[0].lower())
    else:
        # No comma — try both first and last whitespace-separated tokens.
        words = client.split()
        if words:
            candidates.append(words[0].lower())
            if len(words) > 1 and words[-1].lower() != words[0].lower():
                candidates.append(words[-1].lower())
            # For longer names like "Acme Property Management", include
            # the second token too so we match folders that drop the
            # leading word.
            if len(words) > 2:
                candidates.append(words[1].lower())
    # Filter out short tokens that would over-match.
    seen = set()
    out = []
    for t in candidates:
        t = re.sub(r'[^a-z0-9]', '', t)
        if len(t) < 3 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _photo_folder_path(tech, run_date, client):
    """
    Search PHOTOS_ROOT for a folder matching tech+date+client.
    Returns the matched directory path, or None if not found / root unreachable.
    """
    if not os.path.isdir(sharepoint.PHOTOS_ROOT):
        return None

    label       = _tech_initials().get(tech, tech)
    labels      = {tech, label}
    dates       = _date_variants(run_date)
    name_toks   = _client_match_tokens(client)
    label_lower = {l.lower() for l in labels}

    def _fuzzy(name):
        nl = name.lower()
        return (any(d in nl for d in dates)
                and any(t in nl for t in name_toks)
                and any(l in nl for l in label_lower))

    try:
        with os.scandir(sharepoint.PHOTOS_ROOT) as it_root:
            for e in it_root:
                if not e.is_dir():
                    continue
                if _fuzzy(e.name):          # root level
                    return e.path
                try:
                    with os.scandir(e.path) as it_sub:
                        for sub in it_sub:
                            if not sub.is_dir():
                                continue
                            if _fuzzy(sub.name):    # one level deep (tech folder)
                                return sub.path
                            try:
                                with os.scandir(sub.path) as it_deep:
                                    for deep in it_deep:
                                        if deep.is_dir() and _fuzzy(deep.name):  # two levels deep
                                            return deep.path
                            except OSError:
                                pass
                except OSError:
                    pass
    except OSError:
        return None

    return None


def _resolve_tech_root_folder(tech, label):
    """Find the SharePoint root folder for this tech.

    Two-pass strategy:
      1. Exact match — PHOTOS_ROOT/<tech> or PHOTOS_ROOT/<label>. This
         is what the original code did; preserved as the fast path.
      2. Starts-with match — scan PHOTOS_ROOT top-level dirs whose name
         starts with the tech name (case-insensitive). Catches
         "Cesar" → "Cesar Salazar", "Pablo" → "Pablo G", "PG" → "PG Photos".

    Preference order when multiple candidates match: exact > full-name
    starts-with > initials starts-with. Returns the path or None.
    """
    if not os.path.isdir(sharepoint.PHOTOS_ROOT):
        return None
    # Pass 1: exact match (fast).
    for cand in (tech, label):
        p = os.path.join(sharepoint.PHOTOS_ROOT, cand)
        if os.path.isdir(p):
            return p
    # Pass 2: starts-with scan. List once, check both name + label
    # candidates. Full name beats initials when both could match — the
    # full name's first 3+ chars is more distinctive than 2-letter
    # initials, which sometimes collide ("AP" inside "Aparna's
    # Apartment Cleaning" etc.).
    try:
        with os.scandir(sharepoint.PHOTOS_ROOT) as it:
            entries = [e.name for e in it if e.is_dir(
                follow_symlinks=False)]
    except OSError:
        return None
    tech_lower = (tech or "").strip().lower()
    label_lower = (label or "").strip().lower()
    full_match = None
    initials_match = None
    for name in entries:
        nl = name.strip().lower()
        if tech_lower and len(tech_lower) >= 3 and nl.startswith(tech_lower):
            if full_match is None:
                full_match = name
        elif (label_lower and label_lower != tech_lower
                and nl.startswith(label_lower)):
            if initials_match is None:
                initials_match = name
    chosen = full_match or initials_match
    return os.path.join(sharepoint.PHOTOS_ROOT, chosen) if chosen else None


def make_folders(jobs, run_date):
    created, skipped = [], []
    for job in jobs:
        client = job["client"]
        for tech in job["techs"]:
            label = _tech_initials().get(tech, tech)   # use initials in folder name

            # Use the SAME fuzzy detector the UI uses to decide "✓ exists"
            # before we consider creating. The previous code only did an
            # exact-path os.path.exists check, which missed folders named
            # with a different date format ("5-13-26" vs "05-13-2026"),
            # a retyped client name (comma added/removed), or any other
            # benign string variant — and a duplicate was created. The
            # detector matches on date-variant + name-token + tech-label
            # at up to 3 nesting levels, so any plausible prior folder is
            # caught regardless of exact spelling.
            existing = _photo_folder_path(tech, run_date, client)
            if existing:
                skipped.append(f"{label} {client} (existing: "
                               f"{os.path.basename(existing)})")
                continue

            tech_folder = _resolve_tech_root_folder(tech, label)
            if tech_folder is None:
                skipped.append(f"{label} — folder not found in SharePoint")
                continue

            name = f"{label} {run_date} {client}"
            path = os.path.join(tech_folder, name)
            # exist_ok defends against the race where two threads / the
            # user double-clicking Create both reach makedirs in parallel.
            # Detection above is already the primary dedupe.
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as ex:
                skipped.append(f"{name} (create failed: {ex})")
                continue
            created.append(name)
    return created, skipped


def _client_from_sp_name(name):
    """Extract the client portion of a SharePoint photo-folder leaf name.
    Strips the date prefix (and any tech-initials prefix that precedes it)
    so "5-3-26 Smith" → "Smith" and "FB 5-3-26 Smith, John" → "Smith, John".
    Returns the name as-is when no date is found."""
    if not name:
        return ""
    m = _SP_DATE_RE.search(name)
    if m:
        return name[m.end():].strip(" -_·")
    return name.strip()


def _audit_base():
    return config.load().get("audit_base") or ""


def _find_od_folder_for_client(client_name):
    """Return the OD job-folder path for a client, or None if no match.
    Walks AUDIT_BASE/<current year> then <previous year>, picking the first
    folder whose name contains the client's last name (word-boundary).
    Network walk — call from a background thread."""
    _base = _audit_base()
    if not client_name or not _base or not os.path.isdir(_base):
        return None
    # Use the last-name token as the search key — handles "Smith, John"
    # → "smith" and "John Smith" → "smith" alike, and avoids matching
    # commas/whitespace inside folder names.
    toks = [t for t in re.split(r'[,\s]+', client_name.strip().lower()) if t]
    if not toks:
        return None
    last = toks[0] if "," in client_name else toks[-1]
    if len(last) < 3:
        return None
    word_re = re.compile(rf'\b{re.escape(last)}\b', re.IGNORECASE)
    from datetime import datetime as _dt
    now_year = _dt.today().year
    for y in (now_year, now_year - 1):
        year_dir = None
        try:
            for d in os.listdir(_base):
                p = os.path.join(_base, d)
                if (os.path.isdir(p) and str(y) in d
                        and not ("LA" in d.upper() and "FIRE" in d.upper())):
                    year_dir = p
                    break
        except OSError:
            continue
        if not year_dir:
            continue
        try:
            for d in os.listdir(year_dir):
                if word_re.search(d):
                    p = os.path.join(year_dir, d)
                    if os.path.isdir(p):
                        return p
        except OSError:
            continue
    return None
