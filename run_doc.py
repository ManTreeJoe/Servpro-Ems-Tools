"""Run-doc parsing logic — locate the daily run .docx, parse its dates,
and pull a client's activity labels.

UI-free (no tkinter): extracted from run_audit_gui.py so the web panels +
the audit logic can find/read the daily run docs without importing the
8K-line Tk module. `run_audit_gui` re-exports these names via a shim, so
the Tk UI and other callers are unaffected. See EMS_Tk_Extraction_Plan.md.
"""
from __future__ import annotations

import os
import re
import calendar as _calendar
from datetime import datetime

import config
import paths
import persistence
from audit_logic import detect_activity, audit_jobs as _audit_jobs_core

# Run-doc + job-folder roots. Resolved lazily from config on every access
# (config.load() is mtime-cached) so a Settings change or department (OC/IE)
# switch is reflected without a restart. `run_doc.RUNS_DIR` / `.AUDIT_BASE`
# still work via the module __getattr__ below; in-module code uses the
# _runs_dir() / _audit_base() getters.
def _runs_dir():
    configured = config.load().get("runs_dir") or ""
    # A mapped archive can open successfully while containing no current
    # Run Docs. Prefer the current per-user SharePoint/OneDrive library when
    # auto-detection finds it; keep the configured path as the fallback.
    try:
        detected = paths.auto_detect().get("runs_dir") or ""
        if detected and os.path.isdir(detected):
            return detected
    except Exception:
        pass
    return configured


def _audit_base():
    return config.load().get("audit_base") or ""


def __getattr__(name):
    if name == "RUNS_DIR":
        return _runs_dir()
    if name == "AUDIT_BASE":
        return _audit_base()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# (month, day, year) -> compiled filename-date regex, so the pattern
# compiles once per date and is reused on every audit re-render.
_RUN_DOC_DATE_RE_CACHE = {}


def _run_doc_date_pattern(d):
    """Compiled filename matcher shared by one-day and month lookups."""
    cache_key = (d.month, d.day, d.year)
    pattern = _RUN_DOC_DATE_RE_CACHE.get(cache_key)
    if pattern is None:
        sep = r"[.\-_/]"
        yy_short = d.year % 100
        # IE uses separated dates; OC also has concatenated .msg names.
        pattern = re.compile(
            rf"(?<!\d)0?{d.month}{sep}0?{d.day}{sep}"
            rf"(?:{yy_short:02d}|{d.year})(?!\d)"
            rf"|(?<!\d)0?{d.month}{d.day:02d}{d.year}(?!\d)")
        _RUN_DOC_DATE_RE_CACHE[cache_key] = pattern
    return pattern


def _month_search_dirs(runs_dir, year, month):
    """Existing folders that may hold one month's run documents."""
    probe = datetime(year, month, 1)
    found = []
    year_root = os.path.join(runs_dir, str(year))
    roots = [runs_dir, year_root]
    # IE stores daily runs under <Daily Run>/<year>/EMS/<month>. Other
    # departments use the same extra division layer for Contents/Recon/Fire.
    # A connected parent folder is therefore not proof the old two-level
    # finder could see a single document.
    for parent in (runs_dir, year_root):
        for division in ("EMS", "FIRE", "Contents", "CONTENT",
                         "Recon", "RECONSTRUCTION"):
            candidate = os.path.join(parent, division)
            if os.path.isdir(candidate):
                roots.append(candidate)
    for root in roots:
        for month_name in (probe.strftime("%B"), probe.strftime("%b")):
            candidate = os.path.join(root, month_name)
            if os.path.isdir(candidate):
                found.append(candidate)
        if os.path.isdir(root):
            found.append(root)
    # Full/abbreviated month names can resolve to the same folder on a
    # case-insensitive share. Keep one directory scan per actual path.
    out, seen = [], set()
    for path in found:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def run_doc_dates_for_month(year, month):
    """ISO dates in a month that have a .docx or .msg run document.

    The calendar asks for an entire month at once. Scan each candidate
    directory once instead of calling the one-day finder 28–31 times over a
    network/OneDrive folder.
    """
    year, month = int(year), int(month)
    if year < 2000 or year > 2100 or month < 1 or month > 12:
        raise ValueError("invalid calendar month")
    runs_dir = _runs_dir()
    if not runs_dir or not os.path.isdir(runs_dir):
        return []
    names = []
    for folder in _month_search_dirs(runs_dir, year, month):
        try:
            names.extend(name for name in os.listdir(folder)
                         if name.lower().endswith((".docx", ".msg"))
                         and not name.startswith("~$"))
        except OSError:
            continue
    days = []
    for day in range(1, _calendar.monthrange(year, month)[1] + 1):
        d = datetime(year, month, day).date()
        if any(_run_doc_date_pattern(d).search(name) for name in names):
            days.append(d.isoformat())
    return days


def _extract_date_from_folder_name(name):
    """Pull a date out of a SharePoint folder name. Techs use a few formats:
    `4-23-26 Smith`, `Smith 4/23/26`, `Smith 4.23.2026`. Returns a datetime
    or None — the year `26` is interpreted as 2026 (any 2-digit year < 100
    has 2000 added).
    """
    if not name:
        return None
    m = re.search(r'\b(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})\b', name)
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def _parse_folder_date(date_str):
    """Best-effort parse of a folder-date string like '5-3-26' /
    '05-03-2026' / '5/3/26' / '5.3.26' into a `datetime.date`."""
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in ("%m-%d-%y", "%m-%d-%Y",
                "%m/%d/%y", "%m/%d/%Y",
                "%m.%d.%y", "%m.%d.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_run_doc_for_date(d):
    """Search RUNS_DIR for the daily run .docx that matches a given date.

    Run docs live in `<RUNS_DIR>/<MonthName>/<Weekday> <M.D.YY>.docx` (with
    occasional trailing whitespace before .docx). The date portion of
    filenames is inconsistent across techs:
        '4.10.26'   '04.10.26'   '4-10-26'   '4_10_26'   '4.10.2026'
    All of those are valid for the same date. We tolerate any combination
    of leading zero on month/day, 2- vs 4-digit year, and any of
    `.`, `-`, `_`, `/` as separators by matching with a regex.

    Tries the full month name first, then the 3-letter abbreviation since
    the user has both forms in their archive (e.g. 'Feb' alongside 'April'),
    and finally falls back to RUNS_DIR itself for files saved without a
    monthly subfolder.

    Returns the absolute path of the first matching .docx, or None.
    """
    runs_dir = _runs_dir()
    if not d or not runs_dir or not os.path.isdir(runs_dir):
        return None
    month_full = d.strftime("%B")
    month_abbr = d.strftime("%b")
    pattern = _run_doc_date_pattern(d)

    # Search both the run root and a `<root>\<year>` level — IE stores
    # docs as <root>\<Month>\..., but OC nests by year first
    # (<root>\2026\<Month>\...). Checking both means the run folder can be
    # pointed at either the year folder or its parent and still resolve,
    # and it survives the year rollover without a settings change.
    search_dirs = _month_search_dirs(runs_dir, d.year, d.month)

    for sd in search_dirs:
        try:
            entries = os.listdir(sd)
        except OSError:
            continue
        for f in entries:
            # IE run docs are Word .docx; OC's are Outlook .msg emails.
            if not f.lower().endswith((".docx", ".msg")):
                continue
            if pattern.search(f):
                return os.path.join(sd, f)
    return None


# PICS stage folders, mirroring web_shared/stage_picker.js PICS_STAGES.
# A suggestion is only worth making if it names a folder that actually
# exists, so anything detect_activity expects which ISN'T one of these
# (Contents, Pack-out) is dropped rather than offered.
_PICS_STAGES = (
    "Initial", "Reinspection", "Demo", "Mold Prep", "Post Mold Prep",
    "Mold", "Abatement", "Monitor", "Post", "Equipment",
)


def _run_doc_activity_info(folder_date_str, client_name):
    """`detect_activity` output for a client on a folder-date, or None.

    Shared by the label lookup and the stage suggester so both find the
    client the same way — two matchers would eventually disagree about
    which run-doc line belongs to which job.
    """
    if not folder_date_str or not client_name:
        return None
    d = _parse_folder_date(folder_date_str)
    if not d:
        return None
    try:
        doc_path = _find_run_doc_for_date(d)
    except Exception:
        doc_path = None
    if not doc_path:
        return None
    try:
        from state_hub import hub as _hub
        jobs, _date = _hub.parse_run_doc(doc_path)
    except Exception:
        jobs = []
    canon = re.sub(r"\s+", " ", (client_name or "").strip().lower())
    matched = None
    for j in jobs:
        jc = re.sub(r"\s+", " ",
                      (j.get("client") or "").strip().lower())
        if jc == canon:
            matched = j
            break
    if matched is None:
        for j in jobs:
            jc = re.sub(r"\s+", " ",
                          (j.get("client") or "").strip().lower())
            if canon and (canon in jc or (len(jc) >= 4
                                            and jc in canon)):
                matched = j
                break
    if matched is None:
        return None
    try:
        return detect_activity(
            matched.get("raw") or "",
            section=matched.get("section"),
            new_loss=matched.get("new_loss"))
    except Exception:
        return None


def suggest_pics_stage(folder_date_str, client_name):
    """The PICS stage this client's run-doc line implies for that day.

    CompanyCam routes photos by their own tags, but plenty arrive
    untagged — and then someone has to remember what that visit was and
    pick a stage by hand, days later. The run doc already recorded what
    was scheduled, so this answers it from the day's own record.

    Returns "" when there's no run doc, no matching client, or the
    activity maps to no real PICS folder. A wrong guess files photos
    where nobody would look for them, so "no idea" has to stay sayable.
    """
    info = _run_doc_activity_info(folder_date_str, client_name)
    if not info:
        return ""
    for folder in (info.get("expected") or []):
        if folder in _PICS_STAGES:
            return folder
    # Monitor carries no expected folder (it needs no photos) but IS a
    # real stage — a monitor visit that did produce photos belongs there.
    for label in (info.get("labels") or []):
        if label in _PICS_STAGES:
            return label
    return ""


def _activity_labels_from_run_doc(folder_date_str, client_name):
    """Return the raw activity labels (e.g. ['Demo', 'Mold Prep']) for a
    client on a given folder-date, by locating that day's run-doc and
    matching the client row. Used by the IUQ/audit PICS-subfolder
    resolver to decide where photos land. Returns [] when no run-doc or
    matching client is found."""
    info = _run_doc_activity_info(folder_date_str, client_name)
    return list((info or {}).get("labels") or [])


def _composed_folder_lookup(run_date, *, base=None, expand_map=None):
    """Return a `folder_path_lookup(client) -> path|None` that checks
    in this order:
      1. `expand_map` — multi-unit expansion lookup keyed by the
         augmented client name ("Avila Apartments — Unit 527").
         Bypasses everything else so each expanded child resolves to
         the unit the user picked.
      2. `base` (caller's one-shot override, when supplied) — wins so
         the "pick this folder for today's audit" dialog can preempt
         persisted state.
      3. Per-day unit pin for `run_date` (`persistence.set_run_day_unit`)
         — the user's "for today's run, this Avila row → this folder"
         pick from the 🏠 Unit picker.
      4. Permanent folder pin (`persistence.get_folder_path`) — the
         Find Folder memory.

    Composing here (rather than threading four lookup args through
    audit_jobs) keeps audit_logic.audit_jobs unchanged."""
    def _lookup(client):
        if expand_map:
            hit = expand_map.get(client)
            if hit:
                return hit
        if base is not None:
            try:
                hit = base(client)
            except Exception:
                hit = None
            if hit:
                return hit
        if run_date:
            try:
                day_hit = persistence.get_run_day_unit(run_date, client)
            except Exception:
                day_hit = ""
            if day_hit:
                return day_hit
        try:
            return persistence.get_folder_path(client)
        except Exception:
            return None
    return _lookup


def audit_jobs(client_names, year=None, run_date=None, use_cache=True,
               folder_path_lookup=None, expand_map=None, progress_cb=None,
               expand_subjobs=False):
    """Thin wrapper around `audit_logic.audit_jobs` that supplies the
    AUDIT_BASE config and the per-day → permanent folder lookup chain.
    Callers can pass their own `folder_path_lookup` to layer a one-shot
    override (e.g., the Audit One Job dialog's picked folder) on top of
    the chain. `expand_map` is the multi-unit replication map built by
    `_expand_multi_pinned_jobs` — augmented client names lookup
    directly to their pinned unit folder.

    `progress_cb`: optional `(idx, total, client_name)` callback fired
    once per job audited — lets the web/Tk UIs stream per-job progress
    events back instead of staring at a frozen spinner."""
    lookup = _composed_folder_lookup(
        run_date, base=folder_path_lookup, expand_map=expand_map)
    return _audit_jobs_core(
        client_names,
        _audit_base(),
        year=year,
        folder_path_lookup=lookup,
        run_date=run_date,
        use_cache=use_cache,
        progress_cb=progress_cb,
        expand_subjobs=expand_subjobs,
    )


# ══ Run-doc parsing ═════════════════════════════════════════════════
# Lifted verbatim from run_audit_gui (an 8K-line tkinter module) so the
# web panels, initial_upload_queue, sp_recent_audit and state_hub can
# parse a run doc without loading Tk. run_audit_gui re-exports these
# names, so the Tk UI is unaffected. See EMS_Tk_Extraction_Plan.md.
#
# TECH_PATTERN / ABBREV are read as audit_logic attributes rather than
# imported by value: audit_logic REBINDS both when the tech roster
# reloads, so a `from audit_logic import TECH_PATTERN` freezes the
# pattern that existed at import and a newly-added tech stops being
# recognized in run-doc lines until restart. run_audit_gui still has
# that bug for its own copies; this module does not.
import audit_logic
from datetime import timedelta

# Word-boundaries on the alphabetic keywords so 'Suite' doesn't match
# inside 'Suites' (the bug that made "Everhome Suites" parse with
# unit='s' and silently break SP matching). The bare `#` branch:
#  * has a leading lookbehind so 'foo#123' never matches — must be
#    preceded by whitespace or start-of-string, ruling out hashes
#    embedded in URLs / hex / file extensions.
#  * caps the captured value at 5 chars so a `claim #168240` style
#    line doesn't get parsed as unit=168240. Real apartment numbers
#    are at most ~4 chars (3 digits + optional letter); 5 leaves a
#    little headroom without sweeping in claim-number runs.
#
# NOTE: daily_photos_gui carries a looser copy (no word boundaries,
# unbounded capture). It is deliberately NOT converged here — that
# would change how that panel parses, which is a separate decision.
UNIT_RE = re.compile(
    r'(?:\bunit\b|\bapt\b\.?|\bsuite\b|(?<![\w])#)\s*#?\s*([\w]{1,5})(?!\w)',
    re.IGNORECASE)


def _preserve_mtime(path):
    """Snapshot (atime, mtime) before opening a file we don't intend to modify,
    so we can restore them afterward.

    OneDrive Files-On-Demand bumps the local mtime to "now" the first time a
    cloud-only file is materialized (i.e. read). The file content is
    unchanged but Explorer shows a today's-date "Date modified". Capturing
    here and restoring with os.utime in the caller keeps the displayed
    timestamp stable.

    Returns (atime, mtime) tuple, or None if the file is missing or stat
    fails. Callers should use restore_mtime() to apply it back.
    """
    try:
        st = os.stat(path)
        return (st.st_atime, st.st_mtime)
    except OSError:
        return None


def _restore_mtime(path, snap):
    """Restore the (atime, mtime) captured by _preserve_mtime. Quiet on
    failure — restoration is best-effort and shouldn't crash the caller."""
    if not snap:
        return
    try:
        os.utime(path, snap)
    except OSError:
        pass

# Time-slot extraction. Run-doc lines for new-loss visits and Monitor
# stops often include the appointment window — surfacing that on the
# audit row tells the auditor when the tech is going without having to
# re-open the doc. Common forms in the run doc:
#   "9-11 FB"            → "9-11"
#   "1-3pm FB"           → "1-3pm"
#   "@12pm" / "@9:30am"  → preserved with the @
#   "11:30AM"            → "11:30AM"
# Digit ranges are constrained to 1-12 so we don't false-match phone
# numbers (951-600-1817), zip codes (92591), or street addresses.
_TIME_SLOT_RE = re.compile(
    r'(?:'
    r'@\s*\d{1,2}(?::\d{2})?\s*[ap]m'
    r'|'
    r'\b(?:1[0-2]|[1-9])(?::\d{2})?\s*-\s*'
    r'(?:1[0-2]|[1-9])(?::\d{2})?\s*(?:[ap]m)?'
    r'|'
    r'\b(?:1[0-2]|[1-9]):\d{2}\s*[ap]m'
    r')',
    re.IGNORECASE,
)


def _extract_time_slot(text):
    """Return the time slot mentioned in a run-doc line, or None."""
    if not text:
        return None
    m = _TIME_SLOT_RE.search(text)
    if not m:
        return None
    # Normalize whitespace — "9 - 11" → "9-11" — and lowercase the
    # AM/PM part so the badge reads consistently regardless of source
    # casing ("11:30AM" → "11:30am"). No \b in this sub: "30am" has
    # no word boundary between digit and letter.
    s = re.sub(r'\s*-\s*', '-', m.group(0).strip())
    s = re.sub(r'(?i)(am|pm)', lambda m_: m_.group(1).lower(), s)
    return s

def _parse_run_doc_entries(entries):
    """Core run-doc parser over a list of ``(text, is_struck)`` lines.

    Shared by the `.docx` path (IE — Word paragraphs, real strikethrough)
    and the `.msg` path (OC — Outlook email body lines, no strikethrough).
    Returns ``(jobs, run_date)``; the caller handles merge + run_date
    fallback so this stays format-agnostic."""
    current_section = None
    jobs = []
    run_date = ""
    date_re = re.compile(r'\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b')
    stop_re = re.compile(r'^(upcoming|tbs\b|pending|on hold|marketing)', re.IGNORECASE)

    for text, struck in entries:
        text = (text or "").strip()
        if not text:
            continue
        tl = text.lower()

        if re.search(r'\bdate\b', text, re.IGNORECASE):
            m = date_re.search(text)
            if m and not run_date:
                for fmt in ("%m/%d/%y", "%m/%d/%Y"):
                    try:
                        d = datetime.strptime(m.group(1), fmt)
                        run_date = f"{d.month:02d}-{d.day:02d}-{d.year}"
                        break
                    except Exception:
                        pass

        if "work to be performed" in tl:
            current_section = "work"
            continue
        if re.match(r'^monitor', tl):
            current_section = "monitor"
            continue
        if stop_re.match(tl):
            current_section = None
            continue
        if not current_section:
            continue
        if struck:
            continue
        if re.search(r'\bwarehouse\b', tl):
            continue

        clean = re.sub(r'^\d+\.\s*', '', text).strip()
        # Most run-doc lines look like "Client Name: <address> <phone>
        # (job-type) <techs>" but some are written without a colon —
        # the client name runs straight into the street address, e.g.
        # "Celia Aldana 39613 Oak Cliff Dr, Temecula Ca 92591/...".
        # When the colon is missing, split at the first 2+ digit run
        # (the street number) instead so we don't drop the whole row.
        colon = clean.find(':')
        if colon != -1:
            client      = clean[:colon].strip()
            after_colon = clean[colon+1:]
        else:
            addr_m = re.search(r'\b\d{2,}\b', clean)
            if not addr_m:
                continue
            client      = clean[:addr_m.start()].strip().rstrip(',-—')
            after_colon = clean[addr_m.start():]
        if not client:
            continue
        # Unit marker can appear EITHER side of the colon — sometimes the
        # property prefix encodes it like "Keystone (Unit 168): 168 W. …"
        # rather than after the address. Search the whole line so neither
        # placement gets lost.
        unit_m = UNIT_RE.search(after_colon) or UNIT_RE.search(client)
        unit   = unit_m.group(1) if unit_m else None
        new_loss = bool(re.search(r'\bnew\s+loss\b', clean, re.IGNORECASE))

        # Tenant in parens immediately before the unit marker — e.g.
        # "Keystone-Highland Village (Anibal Humberto) (Unit 168): …"
        # → tenant="Anibal Humberto", client="Keystone-Highland Village".
        # SharePoint photos for unit jobs sometimes get filed under the
        # tenant name rather than the property name, so we surface both.
        tenant = None
        tenant_m = re.search(
            r'\(([^()]+?)\)\s*(?=\((?:unit|apt\.?|suite|#))',
            client, re.IGNORECASE)
        if tenant_m:
            tenant = tenant_m.group(1).strip()
        # Claim hint in parens — "Sayra Mansolino (1s claim)" /
        # "(2nd claim Kitchen)". A job spanning multiple claims on one
        # property is written as separate run-doc lines, each tagged with
        # a parenthetical that mentions "claim". Capture it BEFORE the
        # strip below so (a) the two lines don't merge into one row and
        # (b) the audit can route each to its own claim subfolder.
        claim_hint = None
        _claim_m = re.search(r'\(([^()]*\bclaim\b[^()]*)\)',
                             client, re.IGNORECASE)
        if _claim_m:
            claim_hint = _claim_m.group(1).strip()
        # Strip every (...) group from the client name so the audit's
        # folder-matching code sees just the bare property name.
        client = re.sub(r'\s*\([^()]*\)\s*', ' ', client).strip()
        client = re.sub(r'\s+', ' ', client)

        techs = []
        for m in audit_logic.TECH_PATTERN.finditer(clean):
            resolved = audit_logic.ABBREV.get(m.group(0).upper(), m.group(0).title())
            resolved = re.sub(r'Mark\s+([EL])', lambda x: f"Mark {x.group(1).upper()}", resolved)
            if resolved not in techs:
                techs.append(resolved)

        # Time slot — surfaced on Monitor + new-loss audit rows so the
        # user can see when the tech is heading out without re-opening
        # the run doc. Only meaningful when the line actually mentions
        # one; check_photos / aging logic doesn't use it.
        time_slot = _extract_time_slot(text)
        jobs.append({"client": client, "tenant": tenant, "unit": unit,
                     "techs": techs, "new_loss": new_loss,
                     "time_slot": time_slot,
                     "claim_hint": claim_hint,
                     "section": current_section,
                     # `raw` is the original run-doc line — daily_photos_gui
                     # uses it for activity detection, no harm to other
                     # callers since it's just an extra key on the dict.
                     "raw": text})

    return jobs, run_date

def _yesterday_run_date():
    d = datetime.today() - timedelta(days=1)
    return f"{d.month:02d}-{d.day:02d}-{d.year}"


def _run_date_from_msg_name(path):
    """OC `.msg` filenames encode the date as 'Weekday MDDYYYY' (e.g.
    'Monday 7202026' → 7/20/2026). Return 'MM-DD-YYYY' or ''."""
    base = os.path.basename(str(path))
    m = re.search(r'(?<!\d)(\d{1,2})(\d{2})(\d{4})(?!\d)', base)
    if not m:
        return ""
    try:
        d = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        return f"{d.month:02d}-{d.day:02d}-{d.year}"
    except ValueError:
        return ""

def parse_run_doc(path):
    """Parse a daily run doc into ``(jobs, run_date)``. Handles both the
    IE Word `.docx` format and the OC Outlook `.msg` email format — same
    job-list content, different container."""
    p = str(path)
    if p.lower().endswith(".msg"):
        # OC — read the email body, parse its lines (no strikethrough
        # info in plain text, so every listed job is treated as active).
        import msg_reader
        body = msg_reader.read_msg_text(p)
        entries = [(ln, False) for ln in body.splitlines()]
        jobs, run_date = _parse_run_doc_entries(entries)
        if not run_date:
            run_date = _run_date_from_msg_name(p) or _yesterday_run_date()
        return _merge_duplicate_jobs(jobs), run_date

    # IE — Word doc. OD-on-demand can stamp today's mtime when it
    # materializes the file; snapshot before reading and restore after so
    # the user's "Date modified" stays accurate to when the doc was
    # actually edited.
    _ts_snap = _preserve_mtime(p)
    from docx import Document          # lazy: keeps run_doc off the
    from audit_logic import para_is_struck   # docx/lxml stack at import
    doc = Document(p)
    entries = [(para.text, para_is_struck(para)) for para in doc.paragraphs]
    jobs, run_date = _parse_run_doc_entries(entries)
    if not run_date:
        run_date = _yesterday_run_date()
    _restore_mtime(p, _ts_snap)
    return _merge_duplicate_jobs(jobs), run_date

def _merge_duplicate_jobs(jobs):
    """Collapse repeat run-doc lines for the same client+unit into a
    single job entry. Run docs sometimes mention a job twice (morning
    vs afternoon crew, or once under Work and again under Monitor as a
    reminder). The audit treats each line as a separate row, which
    surfaces the same client multiple times and re-runs every check.

    Merge rules:
      • Key:       (client_normalized, unit) — case/whitespace folded
                   so "Joe Smith" and "joe  smith" collapse together.
      • techs:     union, preserving first-seen order.
      • new_loss:  any True wins.
      • section:   prefer 'work' over 'monitor' — photo expectations
                   only fire for work, and a client appearing in BOTH
                   sections should be audited as a work job.
      • raw:       newline-join all source lines so detect_activity
                   sees every keyword (e.g. one line says 'Demo' and
                   the other says 'Mold Prep')."""
    if not jobs:
        return jobs

    def _key(j):
        c = " ".join((j.get("client") or "").lower().split())
        u = (j.get("unit") or "").strip().lower()
        # Distinct claims on one property are written as separate lines
        # tagged "(1s claim)" / "(2nd claim Kitchen)" — keep them apart so
        # they don't collapse into a single audit row. Key on the claim
        # NUMBER so "(1s claim)" and "(1st claim)" for the SAME claim still
        # merge (true duplicate reminders).
        cn = audit_logic.claim_number_from_hint(j.get("claim_hint") or "")
        return (c, u, cn)

    merged = {}
    order = []
    for j in jobs:
        k = _key(j)
        if k not in merged:
            # Shallow copy so we can mutate techs/raw without touching
            # the source dict (parsers downstream may still hold refs).
            merged[k] = {**j, "techs": list(j.get("techs") or [])}
            order.append(k)
            continue
        m = merged[k]
        for t in (j.get("techs") or []):
            if t not in m["techs"]:
                m["techs"].append(t)
        if j.get("new_loss"):
            m["new_loss"] = True
        # Tenant — prefer the first occurrence; promote a second-line
        # tenant only if the first didn't have one.
        if not m.get("tenant") and j.get("tenant"):
            m["tenant"] = j["tenant"]
        # Time slot — same first-wins rule. The dispatch info usually
        # only appears once anyway, but if both lines have a slot, keep
        # the one that was parsed first.
        if not m.get("time_slot") and j.get("time_slot"):
            m["time_slot"] = j["time_slot"]
        # 'work' beats 'monitor' beats anything else (None).
        if j.get("section") == "work":
            m["section"] = "work"
        elif m.get("section") != "work" and j.get("section") == "monitor":
            m["section"] = "monitor"
        existing_raw = m.get("raw") or ""
        new_raw = j.get("raw") or ""
        if new_raw and new_raw not in existing_raw.split("\n"):
            m["raw"] = (existing_raw + "\n" + new_raw) if existing_raw else new_raw
    return [merged[k] for k in order]
