"""Shared audit helpers — used by snapshot_gui and run_audit_gui."""
import os
import re
import threading
import time as _time
from datetime import date, datetime, timedelta


# ── Year-folder listing cache (TTL'd) ──────────────────────────────────────
# Listing X:\IE_Public\YYYY is an SMB call that returns 1000+ entries.
# A typical audit session runs the daily audit, then snapshot, then audit
# again — re-listing 4 times per session burns several seconds. Cache
# the per-year listing in-memory with a short TTL so repeated audits
# inside the cache window skip the SMB walk entirely.
#
# Trade-off: a brand-new client folder created mid-session won't appear
# until the cache expires. 5 minutes is short enough to feel fresh and
# long enough to short-circuit the typical click-pattern of running
# audit > snapshot > audit.
_YEAR_INDEX_TTL_S = 300  # 5 minutes
_year_index_cache = {}   # {year_folder_path: (timestamp, [name, ...])}
_year_index_lock = threading.Lock()


def _cached_year_listing(year_folder_path, force_refresh=False):
    """Return the directory entries for a year-folder path, using the
    in-memory cache when it's still fresh. Returns [] on OSError.

    Reads outside the lock so concurrent audits don't serialize on the
    cache lookup; writes inside the lock for safety. The lock window
    is microseconds — measurably faster than serializing all readers.
    """
    if not year_folder_path:
        return []
    now = _time.time()
    if not force_refresh:
        cached = _year_index_cache.get(year_folder_path)
        if cached and (now - cached[0]) < _YEAR_INDEX_TTL_S:
            return cached[1]
    try:
        with os.scandir(year_folder_path) as it:
            entries = [e.name for e in it
                       if e.is_dir(follow_symlinks=False)]
    except OSError:
        entries = []
    with _year_index_lock:
        _year_index_cache[year_folder_path] = (now, entries)
    return entries


def invalidate_year_index_cache():
    """Force the next audit to re-listdir every year-folder. Called by
    the audit panel's Full re-scan button."""
    with _year_index_lock:
        _year_index_cache.clear()


# ── Activity-type detection ──────────────────────────────────────────────────
# Reads a run-doc line for activity keywords so the daily-photos and audit
# tools can agree on (a) whether photos are even needed for this job and
# (b) which stage subfolders to expect under PICS. Lives here (not in
# daily_photos_gui or run_audit_gui) so the run-audit photo checker and the
# folder-creation flow can never drift apart on which stages mean which
# folders.
#
# Order matters: more-specific keywords go first so "Mold Prep" doesn't
# fall through to a generic "Mold" rule. job_notes_gui keeps its OWN
# stage table because note-text parsing has different needs (matches
# bare "initial"/"inspection" without "new loss"; does not match
# "contents"/"pack-out" — those don't move the timeline) — don't try
# to merge the two unless you can preserve every contextual nuance.
_ACTIVITY_PATTERNS = [
    # (label, regex, photos_needed, expected_folder_labels)
    ("Mold Prep",          r"\bmold\s*prep\b",            True,  ["Mold Prep", "Post Mold Prep"]),
    ("Demo",               r"\bdemo\b",                   True,  ["Demo", "Post"]),
    ("Contents",           r"\bcontents?\b",              True,  ["Contents"]),
    ("Pack-out",           r"\bpack[\s-]?out\b",          True,  ["Contents", "Pack-out"]),
    ("Pack-in",            r"\bpack[\s-]?in\b",           True,  ["Contents", "Pack-in"]),
    ("Reinspection",       r"\breinspection\b",           True,  ["Reinspection"]),
    ("Initial Inspection", r"\b(initial\s+inspection|new\s+loss)\b", True,  ["Initial"]),
    ("Teardown",           r"\btear[\s-]?down\b",         True,  ["Post"]),
    ("Mold Clearance",     r"(\bmold\s+clear|clearance.*pass)", False, []),
    ("Monitor",            r"\bmonitor\b",                False, []),
]


def make_folder_lookup(override_path=None, override_name=None,
                        base_lookup=None):
    """Build a `folder_path_lookup` callable for audit_jobs.

    Two callers — Run Audit's "Audit One Job" and Snapshot's
    "Audit Only" — wanted the same behavior: when the user picks an
    exact folder for one specific insured, route that path back when
    audit_jobs queries the matcher for that name; otherwise fall back
    to the persistence-backed Find-Folder memory. Doing the build in
    one place stops the lambda's case-folding / fallback-chain logic
    from drifting between panels.

    Pass `base_lookup=None` to default to `persistence.get_folder_path`.
    Pass `override_path=None` to skip the override layer entirely (the
    no-pick code path)."""
    import persistence as _persistence
    base = base_lookup or _persistence.get_folder_path
    if not override_path:
        return base
    target = (override_name or "").strip().lower()
    def _lookup(n, _o=override_path, _t=target, _b=base):
        if _t and n.strip().lower() == _t:
            return _o
        return _b(n)
    return _lookup


def resolve_pics_subfolder(activity_labels):
    """Pick the PICS subfolder name for photos when the run-doc tells us
    what the tech is doing today. Returns (folder_name, needs_prompt):
      - ``folder_name`` — the target subfolder under PICS, or None when
        the operator must disambiguate (needs_prompt=True).
      - ``needs_prompt`` — True only on the Demo + Mold Prep collision,
        where photos can belong to either / both and only the operator
        knows by glancing at the contents.

    User-defined routing rules:
      • Demo absorbs Pack-out / Contents / Pack-in — those photos
        land under Demo, never under Contents.
      • Demo + Mold Prep → prompt: user picks Demo, Mold Prep, or
        both (copy to both folders).
      • Initial Inspection → renders as "Initial" (folder convention).
      • Otherwise → first matched label in priority order.
      • No labels / only Monitor → "Initial" default (matches the
        existing IUQ behavior before activity-based routing).
    """
    labels = [l for l in (activity_labels or [])
              if l and l not in ("Monitor", "Unspecified")]
    if not labels:
        return ("Initial", False)

    has_demo = "Demo" in labels
    has_mold_prep = "Mold Prep" in labels

    # Ambiguous — operator decides which folder (or both).
    if has_demo and has_mold_prep:
        return (None, True)

    # Demo absorbs related staging labels.
    if has_demo:
        return ("Demo", False)
    if has_mold_prep:
        return ("Mold Prep", False)

    # Priority order for the remaining labels.
    priority = [
        ("Initial Inspection", "Initial"),
        ("Contents",           "Contents"),
        ("Pack-out",           "Contents"),  # absorbs to Contents
        ("Pack-in",            "Contents"),
        ("Reinspection",       "Reinspection"),
        ("Teardown",           "Post"),
        ("Mold Clearance",     "Mold Clearance"),
    ]
    for label, folder in priority:
        if label in labels:
            return (folder, False)
    # Fallback — first label as-is.
    return (labels[0], False)


def detect_activity(raw_text, section=None, new_loss=False):
    """Returns a dict with merged activity info from a run-doc line.

    Output: {"labels": [str], "needs_photos": bool, "expected": [str]}
    Falls back to:
      • "Initial" (photos needed) when section=='work' with a new-loss flag,
      • "Monitor" (no photos) when the line is in the monitor section,
      • "Unspecified" (photos needed by default) otherwise.
    """
    matches = []
    for label, pat, needs, folders in _ACTIVITY_PATTERNS:
        if re.search(pat, raw_text or "", re.IGNORECASE):
            matches.append((label, needs, folders))

    if matches:
        labels = [m[0] for m in matches]
        needs_photos = any(m[1] for m in matches)
        expected = []
        for _, _, folders in matches:
            for f in folders:
                if f not in expected:
                    expected.append(f)
        return {"labels": labels, "needs_photos": needs_photos, "expected": expected}

    if new_loss:
        return {"labels": ["Initial"], "needs_photos": True, "expected": ["Initial"]}
    if section == "monitor":
        return {"labels": ["Monitor"], "needs_photos": False, "expected": []}
    return {"labels": ["Unspecified"], "needs_photos": True, "expected": []}


def para_is_struck(para):
    """True if any run in the paragraph has strikethrough.

    Checks both `w:strike` (single) and `w:dstrike` (double) independently
    — a run with strike=false but dstrike=true is still struck through.
    Also honors python-docx's `run.font.strike` attribute as a fallback
    for paragraphs whose strike formatting lives at the run-level rather
    than the rPr element.
    """
    # Imported here, not at module scope: `from docx.oxml.ns import qn`
    # pulls the whole python-docx package (and lxml) in, and audit_logic
    # is imported by every web panel. Run-doc parsing is the only thing
    # that needs it, so the panels shouldn't pay for it on startup.
    from docx.oxml.ns import qn
    for run in para.runs:
        rpr = run._r.find(qn('w:rPr'))
        if rpr is not None:
            for tag in (qn('w:strike'), qn('w:dstrike')):
                el = rpr.find(tag)
                if el is not None and el.get(qn('w:val')) != 'false':
                    return True
        if run.font.strike:
            return True
    return False

# ── Shared tech roster (single source of truth across all tools) ─────────────
#
# `TECH_PATTERN` and `ABBREV` are rebuilt at import time from the hardcoded
# list below + any user-added entries from persistence. Call
# `rebuild_tech_pattern()` after the user edits the roster (via the Tech
# Roster dialog) so live processes pick up new names without restart.

# Names baked into the build. Edit here to add a name shipped with the tool.
# The Tech Roster dialog only manages user-added names — these stay
# regardless of what the user does in the UI.
_HARDCODED_NAMES = [
    "Cesar", "Nestor", "Sam", "Marco", "Danny", "Vince", "Wendy",
    "Robert", "Pablo", "Rudy", "Sergio", "Pris?cilla", "Maria",
    "Brenda", "Elena", "Vicente", "Fernando", "George", "Jose",
    "Aaron", r"Mark\s*E", r"Mark\s*L", "Melvin",
    "FB", "ML", "ME", "GL", "PG", "JL", "AP", "PCB",
]

_HARDCODED_ABBREV = {
    "FB": "Fernando", "ML": "Mark L", "ME": "Mark E",
    "GL": "George",   "PG": "Pablo",
    # JL and AP are their OWN people — not abbreviations for Jose or
    # Aaron Perret. Mapping them to those names was sending JL's jobs
    # into Jose's folder (and AP into a tech who has no folder), which
    # is exactly the behavior the user flagged. Self-map keeps the
    # initials recognized as run-doc tokens without re-routing.
    "JL": "JL",       "AP": "AP",
    "PCB": "PCB",     # initials only — used widely on New Loss lines
}

# Bare first names whose initials ABBREV can't reverse-derive — used only
# by initials_for_name() for display/folder labels, NOT for run-doc routing.
# "John" → JL: the JL code self-maps above (to keep routing correct), so a
# bare "John" upload name has no reverse path without this. Lowercase keys.
_FIRST_NAME_INITIALS = {
    "john": "JL",    # John Lingurar
    "johnny": "JL",  # same person
    "rudy": "RQ",    # Rudy Q — only one Rudy on the roster
    "aaron": "AP",   # Aaron P — only one Aaron on the roster
}


# The tech leads. A lead is who runs an inspection, so this is also the
# set the Initial Inspection email names as Supervisor: a run-doc line
# usually lists the whole crew, and only the lead among them supervised.
TECH_LEADS = (
    "Fernando", "Rudy", "Pablo", "Mark E", "Mark L", "Aaron", "Johnny",
)


def is_tech_lead(name):
    """True when `name` is one of the tech leads, however it was written
    — first name, full name, or roster initials ("FB", "ME")."""
    n = re.sub(r"\s+", " ", str(name or "").strip()).lower()
    if not n:
        return False
    keys = set()
    for lead in TECH_LEADS:
        keys.add(lead.lower())
        ini = (initials_for_name(lead) or "").lower()
        if ini:
            keys.add(ini)
    if n in keys:
        return True
    # "Fernando Baca" / "Mark Escobar" — resolve through the roster so a
    # Trello display name counts too.
    ini = (initials_for_name(n) or "").lower()
    return bool(ini and ini in keys)


def _escape_name_for_regex(name):
    """Names from the user dialog are typed plainly (e.g. "Carlos" or
    "Mark T"). Escape regex metacharacters but allow whitespace between
    tokens to be flexible (so "Mark T" matches "Mark  T" too)."""
    parts = name.split()
    if not parts:
        return ""
    return r'\s*'.join(re.escape(p) for p in parts)


# The pure-initials tokens baked into _HARDCODED_NAMES (recognized on their
# own in run-doc dispatch lines). Once the roster is seeded these live in the
# abbrev map and the pattern picks them up from abbrev KEYS, so we don't seed
# them as standalone "names" (which would show as ugly "FB"-named techs).
_HARDCODED_INITIALS_TOKENS = set(_HARDCODED_ABBREV.keys())


def _clean_builtin_name(raw):
    """Strip the regex bits from a hardcoded roster entry so it reads as a
    plain name ('Mark\\s*E' → 'Mark E', 'Pris?cilla' → 'Priscilla')."""
    return (raw or "").replace(r'\s*', ' ').replace('?', '').strip()


def builtin_seed_names():
    """The hardcoded roster as clean display names, EXCLUDING the pure-
    initials tokens (those seed into the abbrev map instead). Used by the
    one-time migration into the editable user_techs store."""
    out = []
    for raw in _HARDCODED_NAMES:
        if raw in _HARDCODED_INITIALS_TOKENS:
            continue
        cleaned = _clean_builtin_name(raw)
        if cleaned:
            out.append(cleaned)
    return out


def ensure_roster_seeded():
    """One-time migration: copy the built-in names + abbreviations into the
    editable user_techs store, so from then on EVERY tech is user-managed
    (removable/adjustable) and TECH_PATTERN builds from user_techs alone.
    Merges into any existing user entries (keeps additions like 'Uli').
    Idempotent — guarded by persistence.user_techs_seeded(). Returns True if
    it seeded on this call."""
    try:
        import persistence
        if persistence.user_techs_seeded():
            return False
        cur = persistence.get_user_techs() or {}
        names = list(cur.get("names") or [])
        abbrev = dict(cur.get("abbrev") or {})
        have = {n.lower() for n in names}
        for n in builtin_seed_names():
            if n.lower() not in have:
                names.append(n)
                have.add(n.lower())
        for k, v in _HARDCODED_ABBREV.items():
            abbrev.setdefault(k.upper(), v)
        persistence.set_user_techs(names, abbrev)
        persistence.mark_user_techs_seeded()
    except Exception:
        return False
    rebuild_tech_pattern()
    return True


_NEVER_MATCH = re.compile(r'(?!)')   # compiles fine, matches nothing


def _build_tech_pattern():
    """Build the recognized-tech regex.

    Once the roster is seeded (see ensure_roster_seeded), it's built from the
    user_techs store ALONE — names + abbrev-key initials — so a tech the user
    removed truly disappears from recognition. Before seeding (fresh install,
    tests), it falls back to the hardcoded list plus any user additions, so
    behavior is unchanged until the migration runs."""
    seeded = False
    user_names, abbrev_keys = [], []
    try:
        import persistence
        ut = persistence.get_user_techs() or {}
        user_names = list(ut.get("names") or [])
        abbrev_keys = list((ut.get("abbrev") or {}).keys())
        # Read the seeded flag LAST. Setting it first meant a failure in
        # get_user_techs() (corrupt state.json) left seeded=True with an
        # empty roster, which falls into the "empty roster → recognize
        # nothing" branch below and silently stops matching every tech.
        seeded = persistence.user_techs_seeded()
    except Exception:
        pass

    if seeded:
        alts, seen = [], set()
        for name in user_names + abbrev_keys:
            if not name:
                continue
            esc = _escape_name_for_regex(name)
            if esc and esc.lower() not in seen:
                alts.append(esc)
                seen.add(esc.lower())
        if not alts:
            return _NEVER_MATCH        # empty roster → recognize nothing
        return re.compile(r'\b(' + '|'.join(alts) + r')\b', re.IGNORECASE)

    # Pre-seed (legacy): hardcoded + user additions.
    alts = list(_HARDCODED_NAMES)
    seen = {a.lower() for a in alts}
    for name in user_names:
        if not name:
            continue
        esc = _escape_name_for_regex(name)
        if esc and esc.lower() not in seen:
            alts.append(esc)
            seen.add(esc.lower())
    return re.compile(r'\b(' + '|'.join(alts) + r')\b', re.IGNORECASE)


def _build_abbrev():
    """Initials→name map. Once seeded, it's the user_techs abbrev alone;
    before seeding, the hardcoded map plus any user overrides."""
    seeded = False
    user_abbrev = {}
    try:
        import persistence
        seeded = persistence.user_techs_seeded()
        user_abbrev = (persistence.get_user_techs() or {}).get("abbrev", {}) or {}
    except Exception:
        pass
    if seeded:
        return {k.upper(): v for k, v in user_abbrev.items() if k and v}
    out = dict(_HARDCODED_ABBREV)
    for k, v in user_abbrev.items():
        if k and v:
            out[k.upper()] = v
    return out


def rebuild_tech_pattern():
    """Recompute TECH_PATTERN, ABBREV, and TECH_INITIALS_REVERSE in place
    after the user edits the roster. Existing references via
    `audit_logic.TECH_PATTERN` automatically see the new pattern; call
    this anywhere the cached regex needs to refresh."""
    global TECH_PATTERN, ABBREV, TECH_INITIALS_REVERSE
    TECH_PATTERN = _build_tech_pattern()
    ABBREV = _build_abbrev()
    TECH_INITIALS_REVERSE = {v: k for k, v in ABBREV.items()}


TECH_PATTERN = _build_tech_pattern()
ABBREV = _build_abbrev()
TECH_INITIALS_REVERSE = {v: k for k, v in ABBREV.items()}


def initials_for_name(name):
    """Map a free-form tech / uploader name to roster initials.

    Used to label folders + rows by the short tech code the user thinks
    in ("FB", "ME", "ML", "GL") rather than the raw Trello display name.

        "fernando"        -> "FB"   (roster: Fernando)
        "Fernando Baca"   -> "FB"
        "George Lingurar" -> "GL"   (roster: George)
        "Mark Escobar"    -> "ME"   (first+last initial)
        "Mark Lingurar"   -> "ML"
        "FB"              -> "FB"   (already initials)

    Resolution order:
      1. Roster match — TECH_PATTERN finds a known tech token, reverse-
         mapped to its initials (also recognizes an already-initials
         token like "FB"). Honors user-added roster entries.
      2. First-letter-of-first-word + first-letter-of-last-word for a
         multi-word name not in the roster (so two same-first-name techs
         stay distinct: Mark Escobar -> ME vs Mark Lingurar -> ML).
      3. "" when nothing resolves — caller falls back to the raw name.
    """
    if not name:
        return ""
    cleaned = re.sub(r"\s+", " ", name).strip()
    if not cleaned:
        return ""
    # 1) Roster match.
    m = TECH_PATTERN.search(cleaned)
    if m:
        token = re.sub(r"\s+", " ", m.group(1)).strip()
        tok_key = token.upper().replace(" ", "")
        if tok_key in ABBREV:
            return tok_key
        for nm, ini in TECH_INITIALS_REVERSE.items():
            if nm.lower().replace(" ", "") == token.lower().replace(" ", ""):
                return ini
    # 1b) Bare first-name supplement (codes ABBREV can't reverse, e.g. John).
    low = cleaned.lower()
    if low in _FIRST_NAME_INITIALS:
        return _FIRST_NAME_INITIALS[low]
    first = cleaned.split(" ")[0].lower()
    if first in _FIRST_NAME_INITIALS:
        return _FIRST_NAME_INITIALS[first]
    # 2) Multi-word name -> first + last initial.
    parts = [p for p in cleaned.split(" ") if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    # 3) Unresolved.
    return ""


# ── Stable persistence keys ─────────────────────────────────────────────────

_AGING_RE = re.compile(r'^\s*\d+d\s+inactive', re.IGNORECASE)

# Docusketch tour-zip basename pattern (e.g. Tour_123_Order_456_all_sketches7.zip).
# Shared by run_audit_gui, snapshot_gui, and daily_photos_gui — all three need
# to identify Docusketch zips dropped into Downloads for auto-import.
DOCUSKETCH_RE = re.compile(r'Tour_\d+_Order_\d+_all_sketches\d+\.zip',
                            re.IGNORECASE)

# Drying report PDF basename pattern. Phoenix / Thermastor equipment
# dashboards export reports named like `DryingReport_May-29-2026.pdf`.
# Accept the underscored variant the user described plus spaced /
# numeric-date variants so any reasonable naming flows through the
# import detector.
# `.+` (not `\b.*`) — `\b` treats `_` as a word char so it would
# refuse to match `DryingReport_May-29-2026.pdf`. Requiring at least
# one trailing character (date, etc.) also rejects the generic
# `DryingReport.pdf` which is too vague to confidently route.
DRYING_REPORT_RE = re.compile(r'^Drying\s*Report.+\.pdf$',
                                re.IGNORECASE)

def persist_key(item_text):
    """
    Return a stable key for persistence so day-count changes don't lose state.
    '5d inactive (last: 04/18/26)' and '6d inactive (last: 04/18/26)' both
    collapse to 'inactive'. Other issue texts pass through unchanged.
    """
    if _AGING_RE.match(item_text or ""):
        return "inactive"
    return item_text


REQUIRED_FORMS = [
    ("Auth to Perform",      r'auth.*perform|\batp\b'),
    ("Customer Info Form",   r'customer.*info|\bcif\b'),
    ("Customer Equip Resp",  r'customer.*equip|equip.*resp|\bcer\b'),
    ("Cert of Satisfaction", r'cert.*satisf|\bcos\b'),
    ("Scope",                r'\bscope\b'),
]
EXTRA_CARRIERS = ["farmers", "travelers", "lemonade"]
COMMERCIAL_FORM_NAMES = frozenset([
    "auth to perform", "customer info form",
    "customer equip resp", "cert of satisfaction",
])


def is_commercial_form(text):
    return any(n in text.lower() for n in COMMERCIAL_FORM_NAMES)


def _has_files(path):
    if not os.path.isdir(path):
        return False
    try:
        with os.scandir(path) as it:
            return any(True for _ in it)
    except OSError:
        return False


# Multi-claim detection. SERVPRO jobs occasionally span multiple claims
# on the same property (e.g., a roof leak followed months later by a
# water-heater leak). When that happens the staff create a sibling
# sub-folder named with the new claim's ordinal — "Second Claim",
# "2nd Claim", "Claim 2", "Third Claim", etc. — for the new claim's
# paperwork; the original folder retains first-claim files. The audit
# needs to descend into the most-recent claim folder so EMS / PICS /
# DOCS lookups land on the right paperwork.
_CLAIM_ORDINAL_WORDS = {
    "first":  1, "one":   1, "1st":   1, "i":     1,
    "second": 2, "two":   2, "2nd":   2, "ii":    2,
    "third":  3, "three": 3, "3rd":   3, "iii":   3,
    "fourth": 4, "four":  4, "4th":   4, "iv":    4,
    "fifth":  5, "five":  5, "5th":   5,
}
_CLAIM_FOLDER_RES = (
    # "Second Claim" / "2nd Claim" / "II Claim", optionally followed by a
    # parenthetical descriptor — "2nd Claim (Kitchen)". A trailing word
    # that ISN'T parenthetical (e.g. "Second Claim Photos") still fails to
    # match, so a claim sub-asset isn't mistaken for the claim folder.
    re.compile(r"^\s*(\w+)\s+claim\s*(?:\([^)]*\))?\s*$", re.IGNORECASE),
    # "Claim 2" / "Claim #2" / "Claim 02 (Kitchen)"
    re.compile(r"^\s*claim\s*[#]?\s*(\d+)\s*(?:\([^)]*\))?\s*$", re.IGNORECASE),
)

# Matches a claim indicator embedded ANYWHERE in a TOP-LEVEL job-folder
# name — for jobs filed as separate sibling folders per claim
# ("Mansolino, Sayra 1st Claim", "Mansolino, Sayra 2nd Claim (Kitchen)").
# Distinct from `_CLAIM_FOLDER_RES`, which only matches a bare claim
# SUBfolder name. Captures the ordinal so the two siblings can be told
# apart and labeled.
_CLAIM_IN_NAME_RE = re.compile(
    r"\b("
    r"(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth)\s+claim"
    r"|claim\s*#?\s*\d+"
    r")\b",
    re.IGNORECASE)


def has_claim_suffix(folder_name):
    """True when a job-folder name carries a claim indicator (1st Claim,
    2nd Claim, Claim 2, …). Used to detect multi-claim jobs filed as
    separate sibling folders."""
    return bool(_CLAIM_IN_NAME_RE.search(folder_name or ""))


def claim_label_from_folder(folder_name):
    """Return the claim portion of a folder name for display
    ("Mansolino, Sayra 2nd Claim (Kitchen)" → "2nd Claim (Kitchen)"),
    or "" when there's no claim indicator. Keeps any trailing
    parenthetical descriptor since that's how the user distinguishes
    them (e.g. "(Kitchen)")."""
    if not folder_name:
        return ""
    m = _CLAIM_IN_NAME_RE.search(folder_name)
    if not m:
        return ""
    # From the claim indicator to the end of the name (captures the
    # "(Kitchen)" descriptor the user appends).
    return folder_name[m.start():].strip()


def _claim_number_from_folder(name):
    """Return the claim ordinal encoded in a folder name, or None."""
    if not name:
        return None
    s = name.strip()
    for rx in _CLAIM_FOLDER_RES:
        m = rx.match(s)
        if not m:
            continue
        token = m.group(1).strip().lower()
        if token.isdigit():
            try:
                return int(token)
            except ValueError:
                return None
        return _CLAIM_ORDINAL_WORDS.get(token)
    return None


def claim_number_from_hint(text):
    """Claim ordinal pulled from a free-text run-doc hint — the
    parenthetical the user writes to disambiguate a multi-claim line:
    "1s claim" (a common typo for 1st), "1st claim", "2nd claim Kitchen",
    "claim 2", "first claim". Returns the number, or None when the hint
    carries no recognizable ordinal.

    Used to route each run-doc claim line to its matching claim subfolder
    (audit_jobs) and to pair expanded results back to the right run-doc
    line (audit_web._pair_results_to_jobs)."""
    if not text:
        return None
    s = text.strip().lower()
    # A bare/typo'd number wins — "1s" / "1st" / "2nd" / "claim 2".
    m = re.search(r"\d+", s)
    if m:
        try:
            return int(m.group(0))
        except ValueError:
            return None
    # Otherwise an ordinal WORD ("first", "second", roman "ii", …). Only
    # alpha keys here; the digit-bearing keys are handled above.
    for word, n in _CLAIM_ORDINAL_WORDS.items():
        if word.isalpha() and re.search(rf"\b{re.escape(word)}\b", s):
            return n
    return None


def find_latest_claim_subfolder(path):
    """If `path` contains a 'Second Claim' / 'Claim 2' / 'Third Claim'
    sub-folder, return the name of the highest-numbered one. Returns
    None when no claim sub-folder exists. Match is whole-folder-name
    (case-insensitive) so a folder like 'Second Claim Photos' won't
    qualify — it'd be a sub-asset of the active claim, not the claim
    folder itself.

    Used by audit_jobs to descend into the active claim's paperwork
    when a multi-claim job's parent folder still holds first-claim
    files. Exposed so Snapshot / Daily Photos can adopt the same
    behavior later without re-deriving the regex set.
    """
    if not path or not os.path.isdir(path):
        return None
    best = None  # (claim_number, folder_name)
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                n = _claim_number_from_folder(entry.name)
                if n is None:
                    continue
                if best is None or n > best[0]:
                    best = (n, entry.name)
    except OSError:
        return None
    return best[1] if best else None


def active_job_base(path):
    """For a MULTI-CLAIM job folder, return the active (highest-numbered)
    claim subfolder path so paperwork lands under the current claim instead
    of the shared job root. Returns `path` unchanged when the job isn't
    multi-claim. Deterministic — mirrors the descent audit_jobs already does,
    so a save/import can't nondeterministically pick the job root, a stale
    claim, or a top-level DOCS the way a bare find_docs_dir(job_root) did."""
    if not path or not os.path.isdir(path):
        return path
    sub = find_latest_claim_subfolder(path)
    if sub:
        cand = os.path.join(path, sub)
        if os.path.isdir(cand):
            return cand
    return path


# A job folder may hold PAST claims as dated sibling folders ("9-20-25",
# "09.20.2025", "2025-09-20") in addition to the ordinal "Nth Claim" form.
# This matches a folder NAME that is (or starts with) a date so the audit
# can surface historical claims the user wants to revisit.
_DATE_FOLDER_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,2}[-._/]\d{1,2}[-._/]\d{2,4}"      # 9-20-25 / 09.20.2025
    r"|\d{4}[-._/]\d{1,2}[-._/]\d{1,2}"        # 2025-09-20
    r")"
    r"(?:[\s\-_].*)?$",                         # optional trailing descriptor
    re.IGNORECASE)


def claim_folder_kind(name):
    """Classify a subfolder name as a claim/date folder, or None.

    Returns "claim" for ordinal claim folders ("1st Claim", "Second Claim
    (Kitchen)") and any folder whose name starts with the word "claim"
    ("Claim 9-20-25"); "date" for a folder named as a date; else None.
    Standard job subfolders (EMS / PICS / DOCS / CONTENTS / Photos) and
    claim sub-assets ("Second Claim Photos") return None so they aren't
    mistaken for claim folders."""
    if not name:
        return None
    s = name.strip()
    if _claim_number_from_folder(s) is not None:
        return "claim"
    if _DATE_FOLDER_RE.match(s):
        return "date"
    # "Claim 9-20-25" / "Claim A" — starts with the bare word "claim" but
    # NOT a sub-asset like "... Claim Photos" (those have a trailing noun).
    m = re.match(r"^\s*claim\b[\s#:-]*(.+)$", s, re.IGNORECASE)
    if m and not re.search(r"\b(photos?|pics|docs|notes|files?)\b",
                           s, re.IGNORECASE):
        return "claim"
    return None


def list_claim_folders(path):
    """Return the claim / date sibling folders for a job so the audit can
    let the user jump to a PAST claim. Scans `path` AND its parent (so a
    row already resolved into one claim subfolder still surfaces its
    siblings). Each entry:
        {"name", "path", "kind": "claim"|"date", "number", "is_current"}
    Sorted claim-number-desc then name-desc (newest first). Empty list
    when the job has no claim/date subfolders."""
    if not path:
        return []
    seen = {}
    cur_abs = os.path.normcase(os.path.abspath(path))
    scan_dirs = [path]
    parent = os.path.dirname(path.rstrip("\\/"))
    if parent and os.path.isdir(parent):
        scan_dirs.append(parent)
    for d in scan_dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if not e.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    kind = claim_folder_kind(e.name)
                    if not kind:
                        continue
                    full = os.path.join(d, e.name)
                    key = os.path.normcase(os.path.abspath(full))
                    if key in seen:
                        continue
                    seen[key] = {
                        "name":       e.name,
                        "path":       full,
                        "kind":       kind,
                        "number":     _claim_number_from_folder(e.name),
                        "is_current": key == cur_abs,
                    }
        except OSError:
            continue
    def _sort_key(x):
        return (x["number"] if x["number"] is not None else -1, x["name"])
    return sorted(seen.values(), key=_sort_key, reverse=True)


def find_docs_dir(base):
    """Return the existing case-insensitive 'DOCS' subfolder of `base`,
    or None if there isn't one. Used by every tool that needs to drop
    a downloaded form / Docusketch zip into the job's DOCS folder —
    historically each tool inlined this scandir loop, leading to
    bug-fix drift (and the Windows folder-handle leak we just swept).
    Caller is responsible for `os.makedirs(default_docs_path)` if a
    fresh DOCS folder should be created when this returns None."""
    if not os.path.isdir(base):
        return None
    try:
        with os.scandir(base) as it:
            for e in it:
                if e.is_dir() and e.name.upper() == "DOCS":
                    return e.path
    except OSError:
        pass
    return None


def _norm_folder(s):
    """Lowercase, drop everything but letters + spaces, collapse runs.
    Module-level mirror of the closure inside audit_jobs — used by the
    standalone resolver below so callers don't have to spin up a full
    audit pass to ask "does any folder match X"."""
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', (s or "").lower())).strip()


def _toks_folder(norm_s):
    return [t for t in (norm_s or "").split() if len(t) >= 2]


def _match_norm_folder(folder_norm, name_norm):
    return ((len(name_norm) >= 4 and name_norm in folder_norm) or
            (len(folder_norm) >= 4 and folder_norm in name_norm))


def _match_tokens_folder(folder_tokens, name_tokens):
    if len(folder_tokens) < 2 or len(name_tokens) < 2:
        return False
    ftoks = set(folder_tokens)
    ntoks = set(name_tokens)
    return len(ftoks & ntoks) >= 2


def try_resolve_folder_by_terms(audit_base, terms, *, year=None):
    """Standalone folder lookup — given a list of candidate name strings
    (e.g. customer name + address tokens pulled from a Trello card desc),
    return the first unique year-folder hit or None.

    Walks the current + prior year's directory listing once, then tries
    each `term` against folder names with the same _match_norm /
    _match_tokens rules `audit_jobs` uses. A term must yield exactly one
    folder hit to count — ambiguous matches (3+ folders) fall through so
    the user still gets the picker rather than a wrong auto-pin.

    Returns `(absolute_path, folder_basename, year)` on a unique hit, or
    `(None, None, None)` when no term resolves cleanly.
    """
    if not terms or not audit_base or not os.path.isdir(audit_base):
        return (None, None, None)
    current = year or datetime.today().year
    years = [current, current - 1]

    def _find_year_folder(y):
        try:
            with os.scandir(audit_base) as it:
                for e in it:
                    n = e.name
                    if (e.is_dir(follow_symlinks=False)
                            and str(y) in n
                            and not ("LA" in n.upper() and "FIRE" in n.upper())):
                        return e.path
        except OSError:
            return None
        return None

    year_folder_index = {}  # year → [(folder_name, year_path, norm, toks)]
    for y in years:
        yp = _find_year_folder(y)
        if not yp:
            continue
        entries = []
        try:
            with os.scandir(yp) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        n = e.name
                        fn = _norm_folder(n)
                        entries.append((n, yp, fn, _toks_folder(fn)))
        except OSError:
            continue
        year_folder_index[y] = entries

    seen = set()
    for term in terms:
        if not term or not str(term).strip():
            continue
        t = str(term).strip()
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        nl = _norm_folder(t)
        if not nl:
            continue
        ntoks = _toks_folder(nl)
        for y in years:
            entries = year_folder_index.get(y) or []
            hits = [(n, yp) for (n, yp, fn, _ft) in entries
                    if _match_norm_folder(fn, nl)]
            if not hits and len(ntoks) >= 2:
                hits = [(n, yp) for (n, yp, _fn, ft) in entries
                        if _match_tokens_folder(ft, ntoks)]
            if len(hits) == 1:
                name, yp = hits[0]
                return (os.path.join(yp, name), name, y)
            # Multiple matches — don't pick blindly, but keep trying
            # other (more specific) terms before giving up.
    return (None, None, None)


_UNIT_SUBFOLDER_RE = re.compile(
    r"^(unit|apt|apartment|suite|ste|#)\b", re.IGNORECASE)
# Leading unit number (for sorting / routing): "Unit 1416", "1416",
# "1416B", "#527". Tolerates a trailing letter ("1416B") the old
# 2-4 digit `\b` anchor rejected.
_UNIT_NUM_RE = re.compile(r"^\s*#?\s*(?:unit|apt|apartment|suite|ste)?"
                          r"[\s#:_-]*(\d{1,5})", re.IGNORECASE)

# Standard non-unit children of a multi-unit job folder + common junk
# folders. Anything NOT in this set is surfaced as a child so real units
# with off-convention names (1416B, tenant-named "Smith", "Building A")
# stop silently vanishing (audit finding: "exists but not listed").
def _non_unit_children():
    """Shared with job_folders so the two can't drift.

    Both modules answer the same question — "is this subfolder a child job
    or just a container?" — and had grown separate lists. job_folders is
    the lighter module (config + stdlib), so it owns the set; imported
    lazily to keep import order free of surprises.
    """
    try:
        import job_folders
        return job_folders.NON_JOB_CHILD_NAMES
    except Exception:
        return {"ems", "recon", "contents", "docs", "pics", "photos",
                "sp invoices", "receipts", "field docs", "videos",
                "from sharepoint", "old", "backup", "archive",
                "signed docs", "misc", "temp"}


_NON_UNIT_CHILDREN = _non_unit_children()


def _unit_num_of(name):
    """Leading unit number in a folder name, or None for named folders."""
    m = _UNIT_NUM_RE.match(name or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def list_unit_subfolders(parent_path):
    """Return the immediate child subfolders of `parent_path`, EXCLUDING
    only the standard non-unit children / junk (see `_NON_UNIT_CHILDREN`).

    Each item: {"path", "name", "num"} where `num` is the leading unit
    number (int) or None for named children. Numeric units sort first (by
    number), then named folders alphabetically. Returns [] when the parent
    doesn't exist or has no such children.

    Used by Run Audit's 🏠 Unit picker and the umbrella child grouping —
    the exclusion-list approach (vs the old unit/#/digits pattern gate)
    keeps off-convention real units (1416B, "Smith", "Building A") from
    disappearing."""
    if not parent_path or not os.path.isdir(parent_path):
        return []
    out = []
    try:
        with os.scandir(parent_path) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                name = e.name.strip()
                if not name or name.lower() in _NON_UNIT_CHILDREN:
                    continue
                out.append({"path": e.path, "name": name,
                            "num": _unit_num_of(name)})
    except OSError:
        return []
    out.sort(key=lambda d: (d["num"] is None, d["num"] or 0,
                            d["name"].lower()))
    return out


def list_folder_candidates(audit_base, client_name, *, year=None,
                             max_years_back=1):
    """Return every year-folder that matches `client_name`, sorted by
    year descending then folder name. Used by the Run Audit's 🏠 Unit
    picker — when a multi-unit row resolves to the wrong sibling,
    show the user every candidate so they can pick.

    Returns a list of dicts:
        [{"path": str, "name": str, "year": int}, ...]

    Empty when audit_base is unreachable or no folder matches.
    """
    if not client_name or not audit_base or not os.path.isdir(audit_base):
        return []
    current = year or datetime.today().year
    years = list(range(current, current - 1 - max_years_back, -1))

    def _find_year_folder(y):
        try:
            with os.scandir(audit_base) as it:
                for e in it:
                    n = e.name
                    if (e.is_dir(follow_symlinks=False)
                            and str(y) in n
                            and not ("LA" in n.upper() and "FIRE" in n.upper())):
                        return e.path
        except OSError:
            return None
        return None

    nl = _norm_folder(client_name)
    ntoks = _toks_folder(nl)
    out = []
    seen_paths = set()
    for y in years:
        yp = _find_year_folder(y)
        if not yp:
            continue
        try:
            with os.scandir(yp) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            fn = _norm_folder(e.name)
            if not fn:
                continue
            ok = _match_norm_folder(fn, nl)
            if not ok and len(ntoks) >= 2:
                ok = _match_tokens_folder(_toks_folder(fn), ntoks)
            if not ok:
                continue
            full = os.path.join(yp, e.name)
            if full in seen_paths:
                continue
            seen_paths.add(full)
            out.append({"path": full, "name": e.name, "year": y})
    out.sort(key=lambda d: (-d["year"], d["name"].lower()))
    return out


def _latest_mtime(path, depth=2):
    best = None
    try:
        best = os.path.getmtime(path)
        if depth > 0:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        sub = (_latest_mtime(entry.path, depth - 1)
                               if entry.is_dir(follow_symlinks=False)
                               else entry.stat().st_mtime)
                        if sub and (best is None or sub > best):
                            best = sub
                    except OSError:
                        pass
    except OSError:
        pass
    return best


def biz_days_since(dt):
    days, cur, today = 0, dt.date() + timedelta(1), datetime.today().date()
    while cur <= today:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(1)
    return days


def detect_carrier_from_ems(ems_path):
    if not os.path.isdir(ems_path):
        return None
    for fn in os.listdir(ems_path):
        fn_l = fn.lower()
        for carrier in EXTRA_CARRIERS:
            if carrier in fn_l:
                return carrier
    return None


def check_forms(ems_path, carrier=None):
    # Missing EMS folder = nothing on disk to check = every required form
    # is missing. Earlier behavior was to silently return [], which made
    # the audit row look clean for jobs whose EMS folder hadn't been
    # scaffolded yet — masking the gap until somebody noticed days later.
    if not os.path.isdir(ems_path):
        missing = [name for name, _pat in REQUIRED_FORMS]
        if carrier:
            ins = next((c for c in EXTRA_CARRIERS if c in carrier.lower()), None)
            if ins:
                missing.append(f"{ins.title()} forms (0 found, need 3+)")
        return missing
    all_files = []
    # `with` so Windows releases the directory handle immediately —
    # without it, the user can't rename/move job folders while the
    # audit tool is open.
    try:
        with os.scandir(ems_path) as it:
            for e in it:
                if e.is_file():
                    all_files.append(e.name.lower())
                elif e.is_dir() and e.name.upper() == "DOCS":
                    try:
                        with os.scandir(e.path) as it2:
                            for sub in it2:
                                if sub.is_file():
                                    all_files.append(sub.name.lower())
                    except OSError:
                        pass
    except OSError:
        return [name for name, _pat in REQUIRED_FORMS]
    missing = []
    for form_name, pattern in REQUIRED_FORMS:
        if not any(re.search(pattern, fn, re.IGNORECASE) for fn in all_files):
            missing.append(form_name)
    if carrier:
        ins = next((c for c in EXTRA_CARRIERS if c in carrier.lower()), None)
        if ins:
            ins_files = [fn for fn in all_files if ins in fn]
            if len(ins_files) < 3:
                missing.append(f"{ins.title()} forms ({len(ins_files)} found, need 3+)")
    return missing


def check_docusketch(ems_path):
    # Consistent with check_forms: a missing EMS folder means the
    # Docusketch folder is, by definition, also missing. Don't pass
    # silently — the row should call it out so the user knows.
    if not os.path.isdir(ems_path):
        return ["Docusketch folder missing from DOCS"]
    try:
        with os.scandir(ems_path) as it:
            docs_folders = [e.path for e in it
                            if e.is_dir() and e.name.upper() == "DOCS"]
    except OSError:
        return ["Docusketch folder missing from DOCS"]
    if not docs_folders:
        return []
    for docs_path in docs_folders:
        try:
            with os.scandir(docs_path) as it:
                for entry in it:
                    if entry.is_dir() and re.search(r'docusketch|docu.?sketch',
                                                     entry.name, re.IGNORECASE):
                        has_esx = False
                        try:
                            with os.scandir(entry.path) as it2:
                                for sub in it2:
                                    if sub.is_file() and sub.name.lower().endswith('.esx'):
                                        has_esx = True
                                        break
                        except OSError:
                            pass
                        return [] if has_esx else ["Docusketch has no .esx file"]
        except OSError:
            pass
    return ["Docusketch folder missing from DOCS"]


def resolve_pics_dir(base):
    """Return the photos folder for a job (PICS or Photos).

    Some techs file photos under `<base>/Photos` rather than `<base>/PICS`.
    Returns whichever exists; falls back to `<base>/PICS` if neither does
    so callers' downstream "missing PICS" messages stay consistent.
    """
    if not base:
        return ""
    pics = os.path.join(base, "PICS")
    if os.path.isdir(pics):
        return pics
    photos = os.path.join(base, "Photos")
    if os.path.isdir(photos):
        return photos
    return pics


def check_photos(pics_path, log_rows=None, raw_text=None):
    """Check PICS folder for stage-specific subfolders.

    Either source of activity context is fine:
      - `log_rows`  : iterable of (date, weekday, activity, techs)
                      tuples (snapshot/job_notes path).
      - `raw_text`  : the full run-doc line for the job (run-audit
                      path) — `audit_jobs` pulls this from the run
                      doc so callers don't have to derive log_rows.

    Stages checked, only when the activity context mentions them:
      - Demo            → folder matching `\\bdemo\\b`
      - Mold Prep       → `^mold\\s*prep` AND `^post\\s*mold\\s*prep`
      - Mold (general)  → `\\bmold\\b` (ONLY when mold is mentioned
                          but it isn't mold prep — covers mitigation,
                          mold clearance, etc.)
      - Abatement       → `\\babatement\\b`
      - Reinspection    → `\\breinspect`
      - Post (after demo or mold work) → `\\bpost\\b`

    Without any activity context only the Initial pics check fires —
    that matches the legacy behavior callers had before the run-doc
    raw text was plumbed through. WITH activity context the Initial
    pics check only fires when the activity mentions an initial visit
    / new loss / inspection (so mid-mitigation rows don't report
    "Initial pics" missing forever).

    When the PICS folder doesn't exist at all, we treat `entries` as
    empty and let the rest of the function run — every cat_filled()
    check returns False, pics_has_any is False, and Initial + any
    activity-driven stage rows fall out as missing. Consistent with
    check_forms / check_docusketch: a missing folder is a flagged gap,
    not a silent pass."""
    if os.path.isdir(pics_path):
        try:
            entries = os.listdir(pics_path)
        except OSError:
            entries = []
    else:
        entries = []

    def cat_filled(pattern):
        for e in entries:
            if re.search(pattern, e, re.IGNORECASE):
                p = os.path.join(pics_path, e)
                if os.path.isdir(p):
                    return _has_files(p)
                return True
        return False

    # Build a single lowercased text blob from whichever source the
    # caller provided. Both end up just searched for keyword
    # substrings, so a unified blob simplifies the rest of the
    # function.
    activity_blob = ""
    if log_rows is not None:
        activity_blob = " ".join(
            (act or "").lower() for _, _, act, _ in log_rows)
    if raw_text:
        activity_blob = (activity_blob + " " + raw_text.lower()).strip()

    missing = []
    # "Initial" pics may be filed under a folder named "Initial" OR
    # "Inspection" — the inspection IS the initial visit. Flag missing
    # Initial pics when:
    #   • no activity context at all (legacy fallback path), OR
    #   • the activity explicitly mentions an initial visit / new
    #     loss / inspection — i.e. this run actually IS the initial, OR
    #   • the PICS folder is completely empty — a job with zero photos
    #     anywhere is missing the initial regardless of what stage the
    #     run-doc says we're on. Without this third clause, jobs that
    #     never had an initial visit happen but show a mid-mitigation
    #     activity (e.g. Janan Nichols with "Demo" on the run doc but
    #     no photos at all in OD) silently pass the photo check.
    _img_exts = {".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heif",
                 ".webp", ".bmp", ".gif", ".tif", ".tiff"}
    # Budgeted walk: OneDrive/SharePoint enumeration can stall on
    # cold-cache hits or sync hiccups. Cap at 5s and fall back to "no
    # photos found" rather than freeze the audit. Logged so a chronic
    # pattern surfaces in ems.log instead of as a UI hang.
    def _pics_has_any(_path, _exts, _budget=5.0):
        import time as _t
        deadline = _t.monotonic() + _budget
        try:
            for _cur, _dirs, _files in os.walk(_path):
                if _t.monotonic() > deadline:
                    try:
                        import ems_log
                        ems_log.warn("audit_logic",
                                      f"pics_has_any budget exceeded "
                                      f"({_budget}s) for {_path!r}")
                    except Exception:
                        pass
                    return False
                for _f in _files:
                    if os.path.splitext(_f)[1].lower() in _exts:
                        return True
        except OSError:
            return False
        return False
    pics_has_any = _pics_has_any(pics_path, _img_exts)

    # FOH (front-of-house) and EQ (equipment) photos live in their OWN
    # subfolders inside the Initial folder: PICS\Initial\FOH and
    # PICS\Initial\EQ. Resolve the Initial folder once so the FOH/EQ
    # checks below can peek inside it.
    def _initial_dir():
        for e in entries:
            if re.search(r'\b(initial|inspection)\b', e, re.IGNORECASE):
                p = os.path.join(pics_path, e)
                if os.path.isdir(p):
                    return p
        return None

    def _sub_filled(d, pattern):
        """True when the Initial folder `d` contains — at ANY depth — a
        non-empty subfolder matching `pattern` (FOH / EQ). Recursive because
        techs nest these under a "<Tech> <date>" box, e.g.
        PICS\\Initial\\FB 07-01-2026\\Front of Structure — a direct-children
        check missed those. Also still matches a loose file at the top level."""
        if not d or not os.path.isdir(d):
            return False
        try:
            # Recurse: any subfolder (at any level) whose name matches AND
            # holds files satisfies the check.
            for _root, _subdirs, _files in os.walk(d):
                for _sd in _subdirs:
                    if re.search(pattern, _sd, re.IGNORECASE):
                        if _has_files(os.path.join(_root, _sd)):
                            return True
            # Fallback: a loose file at the top level named for the item.
            for s in os.listdir(d):
                if re.search(pattern, s, re.IGNORECASE) and os.path.isfile(
                        os.path.join(d, s)):
                    return True
        except OSError:
            pass
        return False

    _init_dir = _initial_dir()
    needs_initial = (
        not activity_blob
        or 'initial' in activity_blob
        or 'new loss' in activity_blob
        or 'inspection' in activity_blob
        or not pics_has_any
    )
    if needs_initial and not cat_filled(r'\b(initial|inspection)\b'):
        missing.append("Initial pics")

    # FOH (front-of-house) pics are required on the initial visit, at a
    # minimum. Only flagged when the Initial folder itself exists — a
    # missing Initial folder is already reported as "Initial pics", so
    # we don't double-flag the same gap.
    if needs_initial and _init_dir and not _sub_filled(
            _init_dir,
            r'\bfoh\b|\bfos\b|front\s*of\s*(?:house|structure)'):
        missing.append("FOH pics")

    if activity_blob:
        needs_reinspect = 'reinspect' in activity_blob
        needs_demo      = 'demo' in activity_blob
        needs_mold_prep = (
            'mold prep' in activity_blob
            or 'moldprep'  in activity_blob)
        # "Mold After" / "Post Mold" written in the run-doc activity
        # IS the post-mold stage — not a request for generic mold pics
        # AND not a separate post-stage on top. A folder matching
        # post-mold/mold-after satisfies both at once. Without this
        # carve-out the audit double-counts: it would flag generic
        # "Mold pics" missing (because 'mold' is in the activity) AND
        # "Post pics" missing (because 'mold' triggered post). The
        # Buchanan job ("Mold After/Demo") is the canonical case.
        needs_mold_after = (
            'mold after' in activity_blob
            or 'post mold' in activity_blob)
        # General mold work that ISN'T specifically mold-prep or
        # mold-after (mitigation, clearance, "mold clearence" /
        # "Mold Clearance" job-type tags). Skipped when prep or after
        # is mentioned because each has its own dedicated check.
        needs_mold_general = (
            'mold' in activity_blob
            and not needs_mold_prep
            and not needs_mold_after)
        needs_abatement = 'abatement' in activity_blob
        # Generic "post" pics required only when the run-doc explicitly
        # mentions post-stage work. Inferring it from any demo or mold
        # mention generated daily false positives — on the day demo
        # happens, post-demo pics don't exist yet (they come on the
        # next visit). Mold-after / post-mold get their own dedicated
        # check below, so 'mold' alone shouldn't trigger generic post
        # pics either.
        needs_post = (
            'post' in activity_blob
            and not needs_mold_after)
        # EQ (equipment) pics are first needed at the Monitor visit —
        # that's when gear is on site and has to be tracked. They live in
        # PICS\Initial\EQ. Any monitor activity requires the folder to be
        # filled; once it is, later monitors stop flagging.
        needs_eq = 'monitor' in activity_blob

        if needs_reinspect and not cat_filled(r'\breinspect'):
            missing.append("Reinspection pics")
        if needs_demo and not cat_filled(r'\bdemo\b'):
            missing.append("Demo pics")
        # Mold Prep gets its own before/after pair; anchor with ^ so
        # a "Post Mold Prep" folder doesn't satisfy "Mold Prep".
        if needs_mold_prep and not cat_filled(r'^mold\s*prep'):
            missing.append("Mold Prep pics")
        # After-mold-work pics ("Mold After" is the user-preferred
        # name). Single check covers both activity paths:
        #   - "Mold Prep" in activity → need an after-prep folder
        #   - "Mold After" / "Post Mold" in activity → need the same
        # All three folder-naming conventions (`Post Mold Prep`, bare
        # `Post Mold`, `Mold After`) satisfy the check. The label is
        # always "Mold After pics" so the audit row reads with the
        # term the user uses on the run-doc and in conversation.
        if (needs_mold_prep or needs_mold_after) and not cat_filled(
                r'^(post\s*mold(?:\s*prep)?|mold\s*after)'):
            missing.append("Mold After pics")
        if needs_mold_general and not cat_filled(r'\bmold\b'):
            missing.append("Mold pics")
        if needs_abatement and not cat_filled(r'\babatement\b'):
            missing.append("Abatement pics")
        if needs_post and not cat_filled(r'\bpost\b'):
            missing.append("Post pics")
        # EQ folder lives inside Initial (PICS\Initial\EQ). Skip when the
        # Initial folder is absent — "Initial pics" already covers that.
        if needs_eq and _init_dir and not _sub_filled(
                _init_dir, r'\beq\b|equipment'):
            missing.append("EQ pics")
    return missing


def forms_found_in_tree(parent_root, missing_form_names, *,
                        skip_dir=None, max_files=20000):
    """Commercial-parent SUB-JOB fallback for forms.

    A campus sub-job (e.g. "Menifee Union School District \\ Kirkpatrick
    Elementary") audits ONLY its own folder. But a tech may have filed a
    form at the parent root or under a SIBLING campus. Rather than nag it
    as missing, scan the whole parent tree: any of `missing_form_names`
    whose REQUIRED_FORMS pattern matches a file somewhere under
    `parent_root` is MISPLACED, not missing.

    Returns ``{form_label: relative_dir_where_found}`` for whichever
    requested forms turn up. `skip_dir` (the sub-job's own folder) is
    excluded so a form we already know is absent there isn't re-reported.
    Bounded by `max_files` so a huge umbrella tree can't stall the audit.
    """
    wanted = {n: p for (n, p) in REQUIRED_FORMS
              if n in set(missing_form_names or [])}
    if not wanted or not parent_root or not os.path.isdir(parent_root):
        return {}
    skip = (os.path.normcase(os.path.abspath(skip_dir))
            if skip_dir else None)
    found, seen = {}, 0
    try:
        for dirpath, _dirs, filenames in os.walk(parent_root):
            if skip and os.path.normcase(
                    os.path.abspath(dirpath)).startswith(skip):
                continue
            low = [fn.lower() for fn in filenames]
            seen += len(low)
            for name, pat in list(wanted.items()):
                if any(re.search(pat, fn, re.IGNORECASE) for fn in low):
                    try:
                        found[name] = os.path.relpath(dirpath, parent_root)
                    except ValueError:
                        found[name] = os.path.basename(dirpath)
                    del wanted[name]
            if not wanted or seen > max_files:
                break
    except OSError:
        pass
    return found


def photos_found_in_siblings(parent_root, campus_path,
                             missing_photo_labels, raw_text=None):
    """Commercial-parent SUB-JOB fallback for photos / docusketch.

    Mirror of `forms_found_in_tree`: re-runs the photo + docusketch
    checks against the parent root and each SIBLING sub-job folder under
    `parent_root`. A stage label that's missing in THIS campus but
    SATISFIED in another folder is misplaced, not missing.

    Returns ``{label: relative_dir_where_found}``. The campus folder
    itself is skipped (we already know it's missing there).
    """
    want = set(missing_photo_labels or [])
    if not want or not parent_root or not os.path.isdir(parent_root):
        return {}
    campus_norm = (os.path.normcase(os.path.abspath(campus_path))
                   if campus_path else None)
    # Candidates are the SIBLING sub-job folders only — NOT the parent
    # container itself. The container (e.g. "Avila Apartments 2026") has
    # no EMS/DOCS, so check_docusketch/check_photos there return empty
    # ("nothing to check"), which the "satisfied = not missing" test below
    # would mis-read as "found here" and flag EVERY unit's docusketch as
    # misfiled at where='.'. Only real sub-job folders (with their own
    # EMS/CONTENTS/RECON) can legitimately HOLD a misfiled artifact.
    # (Bug fix 2026-06-22 — misfiled tag flagging every commercial unit.)
    candidates = []
    try:
        with os.scandir(parent_root) as it:
            for e in it:
                try:
                    if (e.is_dir(follow_symlinks=False)
                            and _folder_has_job_structure(e.path)):
                        candidates.append(e.path)
                except OSError:
                    continue
    except OSError:
        pass
    found = {}
    for base_dir in candidates:
        if not want:
            break
        if (campus_norm and os.path.normcase(
                os.path.abspath(base_dir)) == campus_norm):
            continue
        ems      = os.path.join(base_dir, "EMS")
        contents = os.path.join(base_dir, "CONTENTS")
        b = (ems if os.path.isdir(ems)
             else contents if os.path.isdir(contents) else base_dir)
        # A label is "found here" only with POSITIVE evidence — the
        # sibling genuinely HAS the artifact. We get that from the
        # sibling's OWN missing-set: a label it does NOT report missing
        # is present there. But guard the docusketch case: check_docusketch
        # returns [] BOTH when a valid .esx exists AND when the folder has
        # no DOCS at all — only the former is real evidence, so require a
        # DOCS folder before crediting a docusketch label as found.
        try:
            dk_missing = set(check_docusketch(b))
            ph_missing = set(check_photos(resolve_pics_dir(b),
                                          raw_text=raw_text))
        except Exception:
            continue
        has_docs = os.path.isdir(os.path.join(b, "DOCS"))
        missing_here = dk_missing | ph_missing
        for label in list(want):
            is_docusketch = "docusketch" in label.lower()
            if is_docusketch and not has_docs:
                continue  # no DOCS folder → not real evidence, skip
            if label not in missing_here:   # present in this sibling
                try:
                    found[label] = os.path.relpath(base_dir, parent_root)
                except ValueError:
                    found[label] = os.path.basename(base_dir)
                want.discard(label)
    return found


def check_initial_photo_report(ems_path):
    if not os.path.isdir(ems_path):
        return ["Initial photo report missing"]
    pat = re.compile(r'photo.*report|initial.*report', re.IGNORECASE)
    try:
        with os.scandir(ems_path) as it:
            for e in it:
                if e.is_file() and pat.search(e.name):
                    return []
                if e.is_dir() and e.name.upper() == "DOCS":
                    try:
                        with os.scandir(e.path) as it2:
                            for sub in it2:
                                if sub.is_file() and pat.search(sub.name):
                                    return []
                    except OSError:
                        pass
    except OSError:
        pass
    return ["Initial photo report missing"]


def inspection_only(log_rows):
    """True if every activity in the log is inspection or reinspection."""
    if not log_rows:
        return False
    return all(
        re.search(r'\b(initial\s+inspection|reinspection)\b', act, re.IGNORECASE)
        for _, _, act, _ in log_rows
    )


# Run-doc lines occasionally tag a job as in audit dispute / rejection.
# When the user sees such a line they have to clear it manually with the
# carrier, so the audit needs to surface that as a flagged item rather
# than silently passing the job because forms+photos look fine.
_DISPUTE_RE   = re.compile(r'\b(dispute(?:s|d)?|disputed)\b', re.IGNORECASE)
_REJECTION_RE = re.compile(
    r'\b(reject(?:ed|ion|ions)?|denial|denied)\b', re.IGNORECASE)


def detect_dispute_notes(raw_text):
    """Return a list of issue strings for any dispute/rejection wording
    found in `raw_text`. Empty list when nothing matches.

    Used by audit_jobs to surface "Address audit dispute" / "Address audit
    rejection" rows so the user can't miss them. Detected per-line so a
    multi-line `raw` (jobs merged from multiple dispatch entries) flags
    each side independently."""
    if not raw_text:
        return []
    issues = []
    saw_dispute = saw_rejection = False
    for line in str(raw_text).splitlines():
        if not saw_dispute and _DISPUTE_RE.search(line):
            issues.append("Address audit dispute (per run-doc note)")
            saw_dispute = True
        if not saw_rejection and _REJECTION_RE.search(line):
            issues.append("Address audit rejection (per run-doc note)")
            saw_rejection = True
        if saw_dispute and saw_rejection:
            break
    return issues


# Subdir names that mark a folder as its OWN job — a child containing one
# is a sub-job, so a parent holding several (a commercial property / school
# district whose sub-jobs are named by site/date, not "Unit X"/"Claim N")
# can fan out into one audit row per sub-job. Mirrors multi_unit_gui.
_JOB_ROOT_DIRS = {"ems", "contents", "recon"}
_SUBJOB_SKIP_DIRS = {"ems", "contents", "recon", "pics", "photos", "docs",
                     "doc", "documents", "forms", "sketch", "sketches",
                     "field docs", "from sharepoint"}


def _folder_has_job_structure(path):
    """True when `path` directly holds an EMS / CONTENTS / RECON subfolder
    — i.e. it's itself a job folder."""
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if (e.is_dir(follow_symlinks=False)
                            and e.name.lower() in _JOB_ROOT_DIRS):
                        return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


def audit_jobs(client_names, audit_base, year=None, folder_path_lookup=None,
               run_date=None, use_cache=True, progress_cb=None,
               expand_subjobs=False):
    """Walk `audit_base/<year>` looking for each client's job folder; for
    each, call check_forms / check_docusketch / check_photos and return a
    list of result dicts plus an optional error message.

    Searches the current year first, then the previous year, so jobs that
    span the new year still resolve. `folder_path_lookup(client_name)`
    (optional) lets the caller override the auto-resolved folder — used
    by run_audit_gui to honor the "Find Folder" persistence memory.

    When `run_date` is supplied and `use_cache` is True, previously-cached
    OK results for unchanged folders are reused instead of re-running the
    forms/photos checks. Flagged results are never cached, so re-runs
    always re-check anything that wasn't fully passing.

    Each result dict:
        client, folder, path, found, form_issues, photo_issues,
        aging, last, flagged
    `flagged` is True if there are any issues OR aging >= 3 business days.
    """
    current_year = year or datetime.today().year
    # Normalize run_date to the "%m-%d-%Y" string the cache + note-logging
    # expect. Callers (e.g. the IUQ enrichment path) pass a date/datetime
    # OBJECT — the per-job note-logging then did strptime(run_date, …),
    # which raises TypeError (only ValueError was caught), and the worker
    # pool swallowed it, so EVERY job dropped → audit_jobs returned 0
    # results. Coerce once here so any caller shape works.
    if isinstance(run_date, date):  # also matches datetime (a date subclass)
        run_date = run_date.strftime("%m-%d-%Y")
    if not os.path.exists(audit_base):
        return None, "Cannot reach X: drive — is it connected?"

    def _find_year_folder(y):
        return next(
            (os.path.join(audit_base, d) for d in os.listdir(audit_base)
             if os.path.isdir(os.path.join(audit_base, d)) and str(y) in d
             and not ("LA" in d.upper() and "FIRE" in d.upper())),
            None)

    years_to_try = [current_year, current_year - 1]
    year_folder_map = {y: _find_year_folder(y) for y in years_to_try}
    year_folder_map = {y: p for y, p in year_folder_map.items() if p}
    if not year_folder_map:
        return None, (f"No {current_year} or {current_year - 1} folder "
                      f"in {audit_base}")

    # Listings come from a process-wide TTL'd cache (see
    # _cached_year_listing above). First audit of a session pays the
    # ~1500-entry SMB walk; subsequent audits within 5 minutes skip
    # it entirely. Full re-scan (use_cache=False) bypasses the cache
    # so a stale listing can't mask a freshly-created job folder.
    #
    # The two year scans run in parallel — the X: drive can absorb
    # two concurrent listings cheaply, and this halves the cold-start
    # listing latency on dual-year sessions.
    year_folder_listing = {}
    force_refresh = not use_cache
    if year_folder_map:
        if len(year_folder_map) == 1:
            (y, yp), = year_folder_map.items()
            year_folder_listing[y] = _cached_year_listing(yp, force_refresh)
        else:
            results_lock = threading.Lock()
            def _walk(y, yp):
                entries = _cached_year_listing(yp, force_refresh)
                with results_lock:
                    year_folder_listing[y] = entries
            scan_threads = [
                threading.Thread(target=_walk, args=(y, yp), daemon=True)
                for y, yp in year_folder_map.items()
            ]
            for t in scan_threads: t.start()
            for t in scan_threads: t.join()

    def _norm(s):
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', s.lower())).strip()

    # Pre-compute normalized folder names per year so the per-client lookup
    # below is just substring matching, not regex over and over. Tokens are
    # also pre-split so the order-insensitive fallback (see _match_tokens
    # below) doesn't re-split per lookup.
    def _toks(norm_s):
        return [t for t in norm_s.split() if len(t) >= 2]
    def _entry(f):
        fn = _norm(f)
        return (f, fn, _toks(fn))
    year_folder_norm = {
        y: [_entry(f) for f in folders]
        for y, folders in year_folder_listing.items()
    }

    def _match_norm(folder_norm, name_norm):
        return ((len(name_norm) >= 4 and name_norm in folder_norm) or
                (len(folder_norm) >= 4 and folder_norm in name_norm))

    def _match_tokens(folder_tokens, name_tokens):
        """Order-insensitive name match — catches the case where the run
        doc has 'John Smith' and the folder is 'Smith, John A 2025'.
        Fires only when both sides contribute ≥2 distinctive tokens AND
        the overlap is ≥2 (so single-name jobs like 'Costco' don't
        bleed across every Costco-named folder)."""
        if len(folder_tokens) < 2 or len(name_tokens) < 2:
            return False
        ftoks = set(folder_tokens)
        ntoks = set(name_tokens)
        return len(ftoks & ntoks) >= 2

    def _reversed_name_candidates(name):
        """Yield possible reversed forms to try when the original doesn't
        match. Multi-word names get multiple rotations because there's no
        way to tell which token is the surname without a name dictionary
        — so we try the two most-likely conventions: last-token-first
        ('Smith, John Adam' = surname + givens) and tail-rotation
        ('Adam Smith John' = mid+last + first)."""
        if ',' in name:
            last, first = [p.strip() for p in name.split(',', 1)]
            yield f"{first} {last}"
            return
        parts = name.strip().split()
        if len(parts) < 2:
            return
        if len(parts) == 2:
            yield f"{parts[1]} {parts[0]}"
            return
        # Multi-word: try last-name-first first (Western folder convention),
        # then the legacy tail-rotation as a backup.
        yield f"{parts[-1]} {' '.join(parts[:-1])}"
        yield f"{' '.join(parts[1:])} {parts[0]}"

    def find_folder_in(name, year, unit=None, tenant=None):
        """Find the best year-folder for `name`. Multi-unit properties
        (Keystone-Highland Village, etc.) often have one folder per unit
        OR per tenant — searching by property name alone can pick up
        the wrong unit's folder. When `unit` or `tenant` is supplied
        and multiple property-name matches exist, prefer the candidate
        whose folder name also encodes the unit number or tenant name.
        Falls back to the first property-only match if no specific
        candidate exists."""
        entries = year_folder_norm.get(year, [])
        if not entries:
            return None
        nl = _norm(name)
        candidates = [(f, fl) for f, fl, _ft in entries if _match_norm(fl, nl)]
        if not candidates:
            for rev in _reversed_name_candidates(name):
                rl = _norm(rev)
                if not rl or rl == nl:
                    continue
                candidates = [(f, fl) for f, fl, _ft in entries
                              if _match_norm(fl, rl)]
                if candidates:
                    break
        if not candidates:
            # Final order-insensitive fallback — handles e.g. run-doc
            # "John Smith" against folder "Smith, John A 2025" where the
            # surname token is in a different position from any of the
            # canonical reversals. Requires ≥2 token overlap so single-
            # word property names don't false-match.
            ntoks = _toks(nl)
            if len(ntoks) >= 2:
                candidates = [(f, fl) for f, fl, ft in entries
                              if _match_tokens(ft, ntoks)]
        if not candidates:
            return None

        # Single property-name match — no disambiguation needed.
        if len(candidates) == 1:
            return candidates[0][0]

        # Multiple candidates — try to lock onto the right unit/tenant.
        # Unit match wins (more specific), tenant is the secondary lever.
        # NOTE: we match against the raw lowercased folder name, NOT the
        # _norm'd form — _norm strips digits so unit numbers vanish.
        if unit:
            un = str(unit).strip().lower()
            if un:
                for folder, _fl in candidates:
                    if re.search(rf'\b{re.escape(un)}\b', folder.lower()):
                        return folder
        if tenant:
            tn = tenant.strip().lower()
            if tn:
                for folder, _fl in candidates:
                    if tn in folder.lower():
                        return folder
        # Fall-through preference order matters for multi-unit
        # commercial properties (Avila Apartments Unit 1413/1416 case
        # 2026-05-26): when `unit` was specified but no candidate
        # folder NAME encodes that unit, we still need to pick the
        # right umbrella so `find_unit` can descend into the matching
        # subfolder. If we just take candidates[0] we might land on a
        # SIBLING per-unit folder (e.g. "Avila Apartments Unit 1413")
        # for a row that wanted Unit 1416 — its subfolder walk would
        # then miss the right unit entirely and the audit/labeling
        # show the wrong folder for that row.
        #
        # Heuristic: when unit was requested but unmatched in any
        # candidate name, prefer the candidate WITHOUT any unit-style
        # token (Unit / Apt / Suite / #) in its name — that's the
        # umbrella. Tokens are detected with the same UNIT_RE-style
        # signal the run-doc parser uses, but inline so audit_logic
        # stays free of run_audit_gui imports.
        if unit:
            _has_unit_token = re.compile(
                r"\b(?:unit|apt|suite)\b|#\s*\d",
                re.IGNORECASE)
            umbrella_first = [(f, fl) for f, fl in candidates
                              if not _has_unit_token.search(f)]
            if umbrella_first:
                return umbrella_first[0][0]
        return candidates[0][0]

    def find_unit(complex_path, unit):
        try:
            with os.scandir(complex_path) as it:
                for e in it:
                    if e.is_dir() and re.search(rf'\b{re.escape(unit)}\b',
                                                 e.name, re.IGNORECASE):
                        return e.name
        except OSError:
            pass
        return None

    # Audit-cache plumbing — only when caller supplied run_date and opted in.
    cache_get = cache_set = None
    if run_date and use_cache:
        try:
            import persistence as _p
            _p.prune_audit_cache()
            cache_get = _p.get_audit_cache_entry
            cache_set = _p.set_audit_cache_entry
        except Exception:
            cache_get = cache_set = None

    # ── Multi-claim expansion ────────────────────────────────────────
    # A client filed as multiple sibling "Nth Claim" folders (e.g.
    # "Mansolino, Sayra 1st Claim" + "Mansolino, Sayra 2nd Claim
    # (Kitchen)") gets ONE audit row per claim folder so both claims are
    # audited independently. Each expanded job's `client` becomes the
    # exact folder name (so persistence / cache / pins stay separate per
    # claim) and carries an explicit `folder_override` path so the name
    # matcher is bypassed (no cross-claim ambiguity). Single-folder jobs
    # pass through untouched.
    def _matching_claim_folders(nm):
        nl = _norm(nm)
        ntoks = _toks(nl)
        seen = {}
        for y in years_to_try:
            yp = year_folder_map.get(y)
            if not yp:
                continue
            for (f, fl, ft) in year_folder_norm.get(y, []):
                if not has_claim_suffix(f):
                    continue
                ok = _match_norm(fl, nl)
                if not ok and len(ntoks) >= 2:
                    ok = _match_tokens(ft, ntoks)
                if ok and f not in seen:
                    seen[f] = os.path.join(yp, f)
        return seen  # {folder_name: full_path}

    # Sibling variant: ONE matching top-level job folder that itself
    # holds ≥2 claim SUBfolders ("Mansolino Sayra\1st Claim" +
    # "Mansolino Sayra\2nd Claim (Kitchen)"). Same outcome as
    # `_matching_claim_folders` — one audit row per claim — but here the
    # claims are nested, so each expanded job pins the PARENT via
    # `folder_override` and names its specific claim in `claim_subfolder`;
    # `_audit_one` descends into that subfolder for the row's checks.
    # Returns (parent_path, [subfolder_name, …]) or (None, []).
    def _matching_claim_subfolders(nm):
        nl = _norm(nm)
        ntoks = _toks(nl)
        for y in years_to_try:
            yp = year_folder_map.get(y)
            if not yp:
                continue
            matches = []
            for (f, fl, ft) in year_folder_norm.get(y, []):
                if has_claim_suffix(f):
                    continue  # top-level siblings handled elsewhere
                ok = _match_norm(fl, nl)
                if not ok and len(ntoks) >= 2:
                    ok = _match_tokens(ft, ntoks)
                if ok:
                    matches.append(f)
            if len(matches) != 1:
                continue  # 0 = no match here; >1 = ambiguous, don't guess
            parent = os.path.join(yp, matches[0])
            subs = []
            try:
                with os.scandir(parent) as it:
                    for e in it:
                        try:
                            if not e.is_dir(follow_symlinks=False):
                                continue
                        except OSError:
                            continue
                        if _claim_number_from_folder(e.name) is not None:
                            subs.append(e.name)
            except OSError:
                continue
            if subs:
                return parent, subs
        return None, []

    # Commercial parent: ONE matching top-level job folder that holds ≥2
    # NAMED sub-job folders (each its own EMS/CONTENTS/RECON job), named by
    # site/date rather than "Unit X" or "Claim N" — e.g. a school district
    # with one folder per campus. Returns (parent_path, [subname, …]) or
    # (None, []). Only consulted when `expand_subjobs` is on (daily run).
    def _matching_subjob_folders(nm):
        nl = _norm(nm)
        ntoks = _toks(nl)
        for y in years_to_try:
            yp = year_folder_map.get(y)
            if not yp:
                continue
            matches = []
            for (f, fl, ft) in year_folder_norm.get(y, []):
                if has_claim_suffix(f):
                    continue
                ok = _match_norm(fl, nl)
                if not ok and len(ntoks) >= 2:
                    ok = _match_tokens(ft, ntoks)
                if ok:
                    matches.append(f)
            if len(matches) > 1:
                # Ambiguous by fuzzy match — but an EXACT name match among
                # them is not ambiguous at all. `_match_tokens` fires on any
                # two shared tokens, and generic words collide hard: every
                # "<Name> Property Management" matches all six others, and a
                # school district matches its own per-campus folder. Without
                # this narrowing the year loop treats the current year as
                # unresolved and falls through to the PRIOR year, so a 2026
                # commercial parent gets audited against its 2025 folder.
                exact = [f for f in matches if _norm(f) == nl]
                if len(exact) == 1:
                    matches = exact
            if len(matches) != 1:
                continue
            parent = os.path.join(yp, matches[0])
            subs = []
            try:
                with os.scandir(parent) as it:
                    for e in it:
                        try:
                            if not e.is_dir(follow_symlinks=False):
                                continue
                        except OSError:
                            continue
                        if e.name.lower() in _SUBJOB_SKIP_DIRS:
                            continue
                        if _claim_number_from_folder(e.name) is not None:
                            continue  # claim subfolders handled above
                        if _folder_has_job_structure(e.path):
                            subs.append(e.name)
            except OSError:
                continue
            if len(subs) >= 2:
                return parent, subs
            # Unique match THIS year but <2 sub-jobs → it's a single job for
            # this year. Stop here; do NOT fall through to an older year's
            # same-named but DIFFERENT job (e.g. the 2026 "Lilia Robles"
            # single job vs. the 2025 "Robles Lilia Apartment" multi-unit —
            # the older one's Apartment 213/214/Hank Greer/Taboo sub-jobs were
            # wrongly grafted onto the current-year parent).
            return None, []
        return None, []

    _expanded = []
    for _job in client_names:
        _nm = _job["client"] if isinstance(_job, dict) else _job
        # (c) Commercial parent with ≥2 NAMED sub-jobs (school district /
        # property whose sub-jobs are named by site/date). Fan out into the
        # PARENT row + one row per sub-job (each pinned to its own full job
        # folder). Runs FIRST — BEFORE the override short-circuit — because
        # the parent's auto-resolved/persisted folder path would otherwise
        # suppress the fan-out. Skip claim-suffixed names + already-expanded
        # sub-job rows (re-audit). Daily-run only (expand_subjobs).
        if (expand_subjobs and not has_claim_suffix(_nm)
                and not (isinstance(_job, dict) and _job.get("subjob"))):
            try:
                _sp, _sjobs = _matching_subjob_folders(_nm)
            except Exception:
                _sp, _sjobs = None, []
            if _sp and len(_sjobs) >= 2:
                # The umbrella head (e.g. "Menifee School District") is a
                # CONTAINER, not a job — flag it so the audit skips its
                # form/photo checks + SP scan and the UI drops the per-job
                # buttons. The real work lives in the campus sub-jobs.
                _pj = (dict(_job) if isinstance(_job, dict)
                       else {"client": _job})
                _pj["is_parent"] = True
                _expanded.append(_pj)
                for _sub in _sjobs:
                    _nj = dict(_job) if isinstance(_job, dict) else {"client": _job}
                    _nj["client"] = _sub
                    _nj["folder_override"] = os.path.join(_sp, _sub)
                    _nj["claim_origin"] = _nm
                    _nj["subjob"] = True
                    _expanded.append(_nj)
                continue
        # A DELIBERATE per-job folder pin (`folder_override` on the dict —
        # e.g. a reaudit row that already resolved to ONE folder) → audit
        # that exact folder, never expand. We intentionally do NOT let a
        # persisted folder_path LOOKUP block expansion: an auto-resolved
        # PARENT (or a stale single-claim) pin must not suppress multi-
        # claim / sub-job fan-out. `_audit_one` still consults the lookup
        # to resolve each non-expanded job's folder — it just no longer
        # halts the expansion here. (A name that already carries a claim
        # suffix is handled by the `has_claim_suffix` check below.)
        if isinstance(_job, dict) and _job.get("folder_override"):
            _expanded.append(_job)
            continue
        # (0) Run-doc already named THIS line's claim — e.g. two lines
        # "Sayra Mansolino (1s claim)" + "(2nd claim Kitchen)" for one
        # property that holds "1st Claim" / "2nd Claim (Kitchen)" claim
        # subfolders. Route this line to the matching subfolder; do NOT
        # fan out (the run-doc already split the claims into separate
        # rows / Trello cards). The parenthetical lives in `claim_hint`
        # (run-doc parser strips it from `client` for folder matching).
        _hint = _job.get("claim_hint") if isinstance(_job, dict) else None
        if _hint:
            _hn = claim_number_from_hint(_hint)
            if _hn is not None:
                try:
                    _hp, _hsubs = _matching_claim_subfolders(_nm)
                except Exception:
                    _hp, _hsubs = None, []
                _pick = None
                if _hp:
                    _pick = next(
                        (s for s in _hsubs
                         if _claim_number_from_folder(s) == _hn), None)
                if _pick:
                    _nj = dict(_job) if isinstance(_job, dict) else {"client": _job}
                    _label = claim_label_from_folder(_pick) or _pick
                    _nj["client"] = f"{_nm} {_label}"   # distinct identity
                    _nj["folder_override"] = _hp        # pin the parent
                    _nj["claim_subfolder"] = _pick      # this row's claim
                    _nj["claim_origin"] = _nm           # bare run-doc name
                    _expanded.append(_nj)
                    continue
            # Hint present but unresolved — fall through to default paths.
        if has_claim_suffix(_nm):
            _expanded.append(_job)
            continue
        # (a) Two-or-more top-level sibling claim folders.
        _claims = _matching_claim_folders(_nm)
        if len(_claims) >= 2:
            for _fname, _fpath in _claims.items():
                _nj = dict(_job) if isinstance(_job, dict) else {"client": _job}
                _nj["client"] = _fname           # distinct identity
                _nj["folder_override"] = _fpath  # bypass matcher
                _nj["claim_origin"] = _nm        # original run-doc name
                _expanded.append(_nj)
            continue
        # (b) One job folder holding ≥2 claim SUBfolders. Best-effort —
        # any folder-walk error falls through to the single-row path,
        # where `_audit_one` still descends into the latest claim.
        try:
            _parent, _subs = _matching_claim_subfolders(_nm)
        except Exception:
            _parent, _subs = None, []
        if len(_subs) >= 2:
            for _sub in _subs:
                _nj = dict(_job) if isinstance(_job, dict) else {"client": _job}
                _label = claim_label_from_folder(_sub) or _sub
                _nj["client"] = f"{_nm} {_label}"   # distinct identity
                _nj["folder_override"] = _parent    # pin the parent
                _nj["claim_subfolder"] = _sub       # this row's claim
                _nj["claim_origin"] = _nm           # original run-doc name
                _expanded.append(_nj)
            continue
        _expanded.append(_job)
    client_names = _expanded

    total = len(client_names)

    def _audit_one(idx_job):
        """Audit a single client. Pure-ish per-job worker that reads
        from the shared (read-only) year-folder index and writes its
        own result dict. Network I/O lives entirely inside this
        function — `_latest_mtime`, `check_forms`, `check_docusketch`,
        `check_photos` — which is why we ship it through a
        ThreadPoolExecutor below: with 8 workers the per-job folder
        walks happen concurrently and a 14-job audit drops from
        ~14× single-job latency to ~2×.
        """
        idx, job = idx_job
        name     = job["client"]       if isinstance(job, dict) else job
        if progress_cb:
            try:
                progress_cb(idx, total, name)
            except Exception:
                pass
        unit     = job.get("unit")     if isinstance(job, dict) else None
        new_loss = job.get("new_loss") if isinstance(job, dict) else False
        techs    = job.get("techs", []) if isinstance(job, dict) else []
        # Tenant from the run-doc (unit jobs only) — passed through to
        # the result so SharePoint matching can search both names.
        tenant   = job.get("tenant")   if isinstance(job, dict) else None
        # Time slot from the run-doc dispatch line (e.g. "9-11", "1-3pm",
        # "@12pm"). Surfaced on Monitor + new-loss rows so the audit
        # tells the user when the tech is going.
        time_slot = job.get("time_slot") if isinstance(job, dict) else None
        # Dispute / rejection wording in the dispatch line — re-derived
        # every run (cheap, depends only on run-doc text) so updates to
        # the run-doc are picked up even when other fields cache hits.
        raw_text = job.get("raw") if isinstance(job, dict) else None
        note_issues = detect_dispute_notes(raw_text)

        # Record today's photographable activities into the per-job
        # ledger up-front — BEFORE the cache lookup — so a fresh Demo /
        # Mold Prep on the run-doc is logged even when the rest of the
        # job's audit hits the cache. Cheap (deduped persistence append).
        run_iso = None
        if run_date:
            for _fmt in ("%m-%d-%Y", "%m-%d-%y"):
                try:
                    run_iso = datetime.strptime(
                        run_date, _fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass
        if run_iso and raw_text:
            try:
                import job_requirements as _jr
                _info = detect_activity(raw_text, new_loss=new_loss)
                _jr.record_from_labels(
                    name, run_iso, _info.get("labels") or [])
            except Exception:
                pass

        # Honor a job-level folder override first (multi-claim expansion
        # pins each claim's exact folder), then the caller's Find-Folder
        # memory, then fall back to the year-folder search.
        job_override = (job.get("folder_override")
                        if isinstance(job, dict) else None)
        override = job_override or (
            folder_path_lookup(name) if folder_path_lookup else None)
        if override and os.path.isdir(override):
            cp          = override
            folder      = os.path.basename(cp)
            found_year  = current_year
            # Multi-unit umbrella correction (Avila Apartments
            # 2026-05-29 case): persistence.get_folder_path is keyed
            # by client name, so both Avila rows reuse the same pin.
            # If a user pinned the "Unit 1413" folder for one row, the
            # 1416 row's override silently became the 1413 folder too
            # and find_unit couldn't descend (1416 isn't nested under
            # 1413). Fix: when the override's basename encodes a unit
            # token AND we're auditing a row with a DIFFERENT unit,
            # walk one level up to the umbrella so find_unit can
            # descend into the row's actual unit subfolder.
            if unit:
                base = os.path.basename(cp.rstrip(os.sep))
                requested = str(unit).strip()
                has_unit_token = re.search(
                    r"\b(?:unit|apt\.?|suite)\b|#\s*\d", base,
                    re.IGNORECASE)
                same_unit = bool(
                    requested and
                    re.search(rf"\b{re.escape(requested)}\b", base,
                               re.IGNORECASE))
                if has_unit_token and not same_unit:
                    parent = os.path.dirname(cp)
                    if parent and os.path.isdir(parent):
                        cp = parent
                        folder = os.path.basename(cp)
        else:
            found_year  = None
            folder      = None
            year_folder = None
            # First pass: prefer a year where the chosen folder name
            # actually encodes this job's unit/tenant. Otherwise the
            # cross-year search silently picks a current-year property
            # match for a DIFFERENT unit instead of the prior-year
            # folder that belongs to this job.
            def _is_specific(folder_name):
                # Match against raw lowercase — _norm strips digits, so
                # unit numbers would silently never match.
                fn = folder_name.lower()
                if unit:
                    un = str(unit).strip().lower()
                    if un and re.search(rf'\b{re.escape(un)}\b', fn):
                        return True
                if tenant:
                    tn = tenant.strip().lower()
                    if tn and tn in fn:
                        return True
                return False

            # Search terms = canonical name + any user-registered aliases
            # (per-client alternate names). Aliases let the user resolve
            # commercial / address-only / nickname mismatches without
            # touching the run-doc.
            try:
                import persistence as _p_aliases
                _search_terms = _p_aliases.client_search_terms(name)
            except Exception:
                _search_terms = [name]

            specific_hit = None
            generic_hit = None
            current = years_to_try[0] if years_to_try else None
            for y in years_to_try:
                if y not in year_folder_map:
                    continue
                f = None
                for _term in _search_terms:
                    f = find_folder_in(_term, y, unit=unit, tenant=tenant)
                    if f:
                        break
                if not f:
                    continue
                if (unit or tenant) and _is_specific(f):
                    specific_hit = (y, f, year_folder_map[y])
                    break
                # For unit/tenant jobs, never accept a non-specific
                # PRIOR-YEAR fallback — a 2025 folder named just
                # "Keystone" is NOT the same job as Keystone-Highland
                # Village (Unit 168) in 2026. Generic current-year
                # matches are still fine (the unit subfolder check
                # downstream will flag if Unit 168 is missing inside).
                if (unit or tenant) and y != current:
                    continue
                if generic_hit is None:
                    generic_hit = (y, f, year_folder_map[y])
            picked = specific_hit or generic_hit
            if picked:
                found_year, folder, year_folder = picked
            if not folder:
                return {"client": name, "path": None, "found": False,
                        "form_issues": [], "photo_issues": [],
                        "note_issues": note_issues,
                        "aging": 0, "last": None, "flagged": True,
                        "techs": techs, "new_loss": new_loss,
                        "tenant": tenant, "unit": unit,
                        "unit_folder": "",
                        "time_slot": time_slot}
            cp = os.path.join(year_folder, folder)

        # Resolved unit subfolder name — surfaced in the audit row's
        # `folder` so the UI can show "Avila Apartments \ Unit 1413"
        # instead of just the property name, and on the row payload
        # as `unit_folder` so the frontend can render a unit chip
        # without re-parsing.
        #
        # Two layouts to handle:
        #   (a) Year-folder = umbrella, unit lives as a subfolder
        #       e.g. .../Avila Apartments/Unit 1413/  →  descend.
        #   (b) Year-folder NAME already encodes the unit
        #       e.g. .../Avila Apartments Unit 1413/   →  no descent,
        #       the year-folder itself IS the resolved unit folder.
        #       Without this branch the row showed the right folder
        #       but the chip rendered AMBER "unit missing" because
        #       `unit_folder` stayed empty — confused the user with
        #       a "wrong labeling" signal even when the audit was
        #       actually on the right folder.
        unit_folder = ""
        if unit:
            sub = find_unit(cp, unit)
            if sub:
                cp = os.path.join(cp, sub)
                unit_folder = sub
                folder = f"{folder} \\ {sub}"
            else:
                # Layout (b): the year-folder name itself encodes
                # the unit. Detect via `\bunit\b` near the requested
                # number — same word-boundary signal find_unit uses
                # on subfolders. When matched, surface the year-
                # folder's last "Unit XXXX" / "Apt XXXX" / "#XXXX"
                # token as unit_folder so the chip renders normally.
                un = str(unit).strip()
                if un:
                    m = re.search(
                        rf"\b(unit|apt\.?|suite)\s*#?\s*{re.escape(un)}\b"
                        rf"|#\s*{re.escape(un)}\b",
                        os.path.basename(cp),
                        re.IGNORECASE)
                    if m:
                        unit_folder = m.group(0).strip()

        # Multi-claim jobs: when the job folder contains a "Second Claim"
        # / "Claim 2" / "Third Claim" sub-folder, that's where the active
        # claim's paperwork lives — descend so EMS / PICS / DOCS lookups
        # below land on the right files. Append the claim suffix to the
        # display folder name so the user sees they're auditing the
        # second-claim subfolder rather than the parent.
        #
        # When the multi-claim expansion pinned a SPECIFIC claim for this
        # row (`claim_subfolder`), descend into exactly that one so each
        # claim gets its own row — otherwise fall back to the latest
        # claim (single-row jobs whose parent still holds prior-claim
        # files).
        claim_sub = job.get("claim_subfolder") if isinstance(job, dict) else None
        if not (claim_sub and os.path.isdir(os.path.join(cp, claim_sub))):
            claim_sub = find_latest_claim_subfolder(cp)
        if claim_sub:
            cp = os.path.join(cp, claim_sub)
            folder = f"{folder} \\ {claim_sub}"

        raw_mt = _latest_mtime(cp, depth=2)
        last   = datetime.fromtimestamp(raw_mt) if raw_mt else None
        aging  = biz_days_since(last) if last else 999

        # Commercial-parent UMBRELLA head: a container, not a job. Don't
        # run form/photo checks (it has no EMS of its own → would show
        # all-red noise) and never flag it. SP enrichment is skipped
        # separately (enrich_with_sharepoint short-circuits is_parent).
        if isinstance(job, dict) and job.get("is_parent"):
            display_folder = (folder if found_year == current_year
                              else f"{folder} ({found_year})")
            return {
                "client":       name,
                "folder":       display_folder,
                "path":         cp,
                "found":        True,
                "form_issues":  [],
                "photo_issues": [],
                "note_issues":  [],
                "aging":        aging,
                "last":         last,
                "flagged":      False,
                "techs":        techs,
                "new_loss":     False,
                "tenant":       "",
                "unit":         "",
                "unit_folder":  "",
                "time_slot":    time_slot,
                "requirements": [],
                "claim_origin": "",
                "subjob":       False,
                "is_parent":    True,
            }

        # Cache lookup — reuse the prior OK result when the folder hasn't
        # changed. Flagged entries were never written, so missing items
        # always fall through to a fresh check. Aging is recomputed every
        # run (cheap, depends only on `last`).
        if cache_get is not None:
            entry = cache_get(run_date, name, unit)
            if (entry
                    and entry.get("path") == cp
                    and entry.get("sig") == raw_mt):
                cached_res = entry.get("result") or {}
                fi = list(cached_res.get("form_issues") or [])
                pi = list(cached_res.get("photo_issues") or [])
                display_folder = cached_res.get(
                    "folder",
                    folder if found_year == current_year
                    else f"{folder} ({found_year})")
                # Recompute day-by-day requirements fresh — only when the
                # job actually HAS a ledger (cheap dict lookup first, so
                # most early-stage jobs skip the PICS walk and still hit
                # the cache). A still-unsatisfied requirement bypasses the
                # cache so the row re-renders with the live photo state.
                _cached_reqs = []
                try:
                    import job_requirements as _jr
                    if _jr.has_ledger(name):
                        _ems  = os.path.join(cp, "EMS")
                        _cont = os.path.join(cp, "CONTENTS")
                        _b = (_ems if os.path.isdir(_ems)
                              else _cont if os.path.isdir(_cont)
                              else cp)
                        _cached_reqs = _jr.compute(
                            name, resolve_pics_dir(_b))
                except Exception:
                    _cached_reqs = []
                if not any(not r.get("satisfied") for r in _cached_reqs):
                    return {
                        "client":       name,
                        "folder":       display_folder,
                        "path":         cp,
                        "found":        True,
                        "form_issues":  fi,
                        "photo_issues": pi,
                        "note_issues":  note_issues,
                        "aging":        aging,
                        "last":         last,
                        "flagged":      (bool(fi) or bool(pi)
                                          or bool(note_issues)
                                          or aging >= 3 or new_loss),
                        "techs":        techs,
                        "new_loss":     new_loss,
                        "tenant":       tenant,
                        "unit":         unit,
                        # Cache-hit path previously dropped unit_folder, so a
                        # clean multi-unit job lost its unit chip on same-day
                        # re-runs. It's already resolved above — carry it.
                        "unit_folder":  unit_folder,
                        "time_slot":    time_slot,
                        "requirements": _cached_reqs,
                        "claim_origin": (job.get("claim_origin")
                                          if isinstance(job, dict)
                                          else "") or "",
                        "subjob":       bool(job.get("subjob"))
                                          if isinstance(job, dict) else False,
                        "from_cache":   True,
                    }
                # else: fall through to a fresh audit so the requirement
                # rows render against current photos.

        ems      = os.path.join(cp, "EMS")
        contents = os.path.join(cp, "CONTENTS")
        if os.path.isdir(ems):
            base = ems
        elif os.path.isdir(contents):
            base = contents
        else:
            base = cp

        fi = check_forms(base)
        pics_dir = resolve_pics_dir(base)
        pi = check_docusketch(base) + check_photos(
            pics_dir, raw_text=raw_text)
        # New-loss is a status tag rendered next to the client name — NOT a
        # checklist item (the .md export still surfaces it explicitly).

        # ── Commercial-parent SUB-JOB fallback ──────────────────────────
        # A campus sub-job (Menifee Union School District \ Kirkpatrick
        # Elementary) is audited against its OWN folder. But a tech may
        # have filed paperwork at the parent root or under a sibling
        # campus. Check the campus folder FIRST (done above), then scan
        # the whole parent tree: anything found there is MISPLACED, not
        # missing — pulled out of fi/pi into misplaced_* with a "where"
        # so the row flags "in <folder>, not in <campus>" instead of a
        # false red. (User decision 2026-06-16: found-but-flag-misplaced.)
        misplaced_forms, misplaced_photos = [], []
        _is_sub = bool(isinstance(job, dict) and job.get("subjob"))
        # Standalone audits (Snapshot / IUQ / re-audit-one) don't carry
        # the Daily-Run `subjob` flag, so detect a commercial-parent
        # campus structurally: ask the SAME name-based matcher the
        # fan-out uses whether THIS folder's parent is a commercial
        # parent with ≥2 named sub-jobs. Safe — it resolves real job
        # folders inside the year roots, so a normal job (whose parent
        # IS the year root) never qualifies. Only when something's
        # actually missing, to bound the extra scan.
        if not _is_sub and (fi or pi):
            try:
                _pdir = os.path.dirname(cp)
                _pp, _subs = _matching_subjob_folders(os.path.basename(_pdir))
                if (_pp and len(_subs) >= 2
                        and os.path.normcase(os.path.abspath(_pp))
                            == os.path.normcase(os.path.abspath(_pdir))):
                    _is_sub = True
            except Exception:
                pass
        # Multi-unit guard: a "Unit 561-J" / "Apt 1017" sub-job is an
        # INDEPENDENT job — each unit has its own paperwork + photos. The
        # cross-sibling misfiled scan only makes sense for shared-paperwork
        # commercial parents (a school district where a tech dumps every
        # campus's photos into one folder). For apartment units, "the
        # sibling unit has its own Scope/docusketch" is normal, not a
        # misfile — scanning siblings there flags every unit as misfiled
        # (the user's "flags everything"). Skip the scan for unit sub-jobs.
        # (2026-06-22)
        #
        # Same logic for multi-CLAIM jobs (Mansolino Sayra 1st Claim / 2nd
        # Claim) — two independent claims filed as sibling folders under one
        # name. Each claim owns its OWN paperwork/photos, so a sibling claim
        # having its own Scope is NOT a misfile. The user: claims "shouldnt
        # be combined in any way". Skip the cross-sibling scan for claim
        # folders too. (2026-06-24)
        _base = os.path.basename(cp)
        _is_unit = bool(re.search(r'(?i)\b(unit|apt|apartment|ste|suite)\b',
                                  _base)) or has_claim_suffix(_base)
        if (_is_sub and not _is_unit and (fi or pi)):
            _parent_root = os.path.dirname(
                job_override or cp)
            try:
                _ff = forms_found_in_tree(_parent_root, fi, skip_dir=cp)
            except Exception:
                _ff = {}
            try:
                _pf = photos_found_in_siblings(
                    _parent_root, cp, pi, raw_text=raw_text)
            except Exception:
                _pf = {}
            if _ff:
                misplaced_forms = [{"label": k, "where": v}
                                   for k, v in _ff.items()]
                fi = [f for f in fi if f not in _ff]
            if _pf:
                misplaced_photos = [{"label": k, "where": v}
                                    for k, v in _pf.items()]
                pi = [p for p in pi if p not in _pf]

        # Day-by-day photo requirements — cumulative list from the ledger
        # (recorded up-front above), each auto-satisfied when a photo
        # dated to that day is on disk. Best-effort.
        requirements = []
        try:
            import job_requirements as _jr
            requirements = _jr.compute(name, pics_dir)
        except Exception:
            requirements = []
        # A job with a still-missing day's photos is flagged so it stays
        # visible AND out of the OK-cache (so the auto-satisfy re-checks
        # against fresh photos on the next run).
        req_unsatisfied = any(not r.get("satisfied") for r in requirements)

        # Tag folder name with year if found in a prior year
        display_folder = (folder if found_year == current_year
                          else f"{folder} ({found_year})")
        result = {
            "client":       name,
            "folder":       display_folder,
            "path":         cp,
            "found":        True,
            "form_issues":  fi,
            "photo_issues": pi,
            "note_issues":  note_issues,
            "aging":        aging,
            "last":         last,
            # New-loss jobs always surface so the user sees the tag, even
            # when paperwork happens to be complete on day-one.
            # Misplaced items keep the row flagged (it needs filing) even
            # though they're no longer counted as "missing".
            "flagged":      (bool(fi) or bool(pi) or bool(note_issues)
                              or aging >= 3 or new_loss
                              or req_unsatisfied
                              or bool(misplaced_forms)
                              or bool(misplaced_photos)),
            "techs":        techs,
            "new_loss":     new_loss,
            "tenant":       tenant,
            "unit":         unit,
            # Resolved unit-subfolder name (e.g. "Unit 1413") when the
            # property is multi-unit AND find_unit located a match.
            # Lets the frontend show the actual descended folder
            # alongside the property name so the admin knows which unit
            # this audit row covered.
            "unit_folder":  unit_folder,
            "time_slot":    time_slot,
            # Day-by-day photo requirements (Demo day 1, Demo day 2, …)
            # accumulated from the run-doc, each auto-satisfied when that
            # day's photos are on disk. Surfaced as a per-row section.
            "requirements": requirements,
            # Original run-doc client name when this row is one of several
            # claim folders expanded from a single line (multi-claim job).
            # Empty for normal single-folder jobs. Lets callers that pair
            # run-doc jobs to results by name re-associate the expanded
            # rows with their source line.
            "claim_origin": (job.get("claim_origin")
                             if isinstance(job, dict) else "") or "",
            "subjob":       bool(job.get("subjob"))
                             if isinstance(job, dict) else False,
            # Items that exist elsewhere in the parent tree (wrong
            # folder), not truly missing. Each: {label, where}.
            "misplaced_forms":  misplaced_forms,
            "misplaced_photos": misplaced_photos,
        }

        # Stash the OK ones for next time — flagged results are skipped by
        # set_audit_cache_entry itself. Strip the datetime field so the
        # JSON serializer in persistence stays unbothered. Note: a job
        # with only a dispute note is `flagged=True` so it's not cached
        # — that's intentional, dispute clearing should re-run the audit.
        # cache_set serializes through persistence's internal lock, so
        # concurrent calls from worker threads are safe.
        if cache_set is not None and not result["flagged"]:
            persisted = {k: v for k, v in result.items() if k != "last"}
            try:
                cache_set(run_date, name, unit, cp, raw_mt, persisted)
            except Exception:
                pass
        return result

    indexed_jobs = list(enumerate(client_names, 1))
    # Daemon-thread worker pool tuned for SMB shares — too many
    # concurrent connections can saturate the share or trigger
    # throttling; 8 is a sweet spot for typical 10–40 job audits.
    # We deliberately roll our own pool instead of using
    # concurrent.futures.ThreadPoolExecutor: that class registers
    # its workers with an atexit hook (`_python_exit`) that BLOCKS
    # interpreter shutdown until every queued task completes — so
    # closing the app mid-audit hung for several seconds while
    # in-flight network walks returned. Plain `daemon=True`
    # threads die instantly on interpreter exit, no join required.
    if total <= 1:
        results = [_audit_one(ij) for ij in indexed_jobs]
    else:
        # 16 workers (was 8). Each per-job task spends most of its
        # time waiting on SMB stat/scandir; Windows can multiplex
        # dozens of in-flight SMB requests over a single share
        # session, so doubling the pool ~halves the wall-clock time
        # for a 30-job audit without saturating the share. Capped at
        # `total` so we don't spawn idle threads when the run-doc is
        # small. Sweet spot for the X:\IE_Public share, profile if
        # you need to tune for a different network topology.
        max_workers = min(16, total)
        out = [None] * len(indexed_jobs)
        next_idx = [0]
        next_lock = threading.Lock()

        def _worker():
            while True:
                with next_lock:
                    if next_idx[0] >= len(indexed_jobs):
                        return
                    i = next_idx[0]
                    next_idx[0] += 1
                ij = indexed_jobs[i]
                try:
                    out[i] = _audit_one(ij)
                except Exception as ex:
                    # A per-job crash must NOT make the client vanish from
                    # the audit (silent N-1 rows the admin can't notice).
                    # Emit a flagged error placeholder so the row still
                    # shows, with the failure surfaced as a note.
                    _, _jobitem = ij
                    _cli = ((_jobitem.get("client")
                             if isinstance(_jobitem, dict) else str(_jobitem))
                            or "?")
                    out[i] = {
                        "client": _cli, "folder": "", "path": "",
                        "found": False, "form_issues": [], "photo_issues": [],
                        "note_issues": [f"Audit error: {type(ex).__name__}: {ex}"],
                        "misplaced_forms": [], "misplaced_photos": [],
                        "aging": 0, "last": None, "flagged": True, "techs": [],
                        "new_loss": False, "tenant": "", "unit": "",
                        "unit_folder": "", "time_slot": "", "requirements": [],
                        "claim_origin": "", "subjob": False,
                        "audit_error": f"{type(ex).__name__}: {ex}",
                    }

        workers = [
            threading.Thread(target=_worker, daemon=True,
                              name=f"audit-{w}")
            for w in range(max_workers)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        results = [r for r in out if r is not None]
    return results, None
