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
from datetime import datetime

import config
import persistence
from audit_logic import detect_activity, audit_jobs as _audit_jobs_core

# Run-doc + job-folder roots. Resolved lazily from config on every access
# (config.load() is mtime-cached) so a Settings change or department (OC/IE)
# switch is reflected without a restart. `run_doc.RUNS_DIR` / `.AUDIT_BASE`
# still work via the module __getattr__ below; in-module code uses the
# _runs_dir() / _audit_base() getters.
def _runs_dir():
    return config.load().get("runs_dir") or ""


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
    yy_short = d.year % 100
    cache_key = (d.month, d.day, d.year)
    pattern = _RUN_DOC_DATE_RE_CACHE.get(cache_key)
    if pattern is None:
        sep = r"[.\-_/]"
        # Two filename date forms:
        #  • IE .docx — separated: "7.20.26" / "7-20-2026" / "7/20/26"
        #  • OC .msg  — concatenated: "7202026" (M + DD + YYYY, no seps)
        pattern = re.compile(
            rf"(?<!\d)0?{d.month}{sep}0?{d.day}{sep}"
            rf"(?:{yy_short:02d}|{d.year})(?!\d)"
            rf"|(?<!\d)0?{d.month}{d.day:02d}{d.year}(?!\d)")
        _RUN_DOC_DATE_RE_CACHE[cache_key] = pattern

    # Search both the run root and a `<root>\<year>` level — IE stores
    # docs as <root>\<Month>\..., but OC nests by year first
    # (<root>\2026\<Month>\...). Checking both means the run folder can be
    # pointed at either the year folder or its parent and still resolve,
    # and it survives the year rollover without a settings change.
    search_dirs = []
    for root in (runs_dir, os.path.join(runs_dir, str(d.year))):
        for mname in (month_full, month_abbr):
            mdir = os.path.join(root, mname)
            if os.path.isdir(mdir):
                search_dirs.append(mdir)
        # Also peek at the root directly — some techs save without the
        # month subfolder. Cheap because os.listdir on a folder we already
        # confirmed exists doesn't add a network round-trip per call.
        if os.path.isdir(root):
            search_dirs.append(root)

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


def _activity_labels_from_run_doc(folder_date_str, client_name):
    """Return the raw activity labels (e.g. ['Demo', 'Mold Prep']) for a
    client on a given folder-date, by locating that day's run-doc and
    matching the client row. Used by the IUQ/audit PICS-subfolder
    resolver to decide where photos land. Returns [] when no run-doc or
    matching client is found."""
    if not folder_date_str or not client_name:
        return []
    d = _parse_folder_date(folder_date_str)
    if not d:
        return []
    try:
        doc_path = _find_run_doc_for_date(d)
    except Exception:
        doc_path = None
    if not doc_path:
        return []
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
        return []
    try:
        info = detect_activity(
            matched.get("raw") or "",
            section=matched.get("section"),
            new_loss=matched.get("new_loss"))
        return list(info.get("labels") or [])
    except Exception:
        return []


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
