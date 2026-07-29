import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import os
import re
import shutil
import threading
import time
import zipfile
import webbrowser
from docx import Document
from datetime import datetime, timedelta
import audit_export
import config
import ctk_helpers as ctkh
import paths
import persistence
import stages
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    TEXT_MUTED, BORDER, FLAG_RED, SURFACE_2,
                    NEUTRAL_HOVER,
                    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
                    INFO_BG, INFO_HOVER, INFO_FG,
                    LINK_BG, LINK_HOVER, LINK_FG,
                    WARN_BG, WARN_HOVER, WARN_FG,
                    DANGER_BG, DANGER_HOVER, DANGER_FG, ON_ACCENT)
from ui_buttons import (
    done_button, send_button, link_button, secondary_button,
    warn_button, icon_button, trello_link_button,
)
from tool_panel import (ToolPanel, run_standalone, show_toast,
                         ResponsiveActionBar, ScrollableFrame,
                         ResponsiveSnap, VirtualizedCardList,
                         attach_tooltip, attach_rich_tooltip)
from job_widgets import (extract_job_year, render_memory_pin,
                          attach_card_context_menu, CommercialToggle,
                          open_trello_pin_dialog)
from trello_icon import trello_icon
from scope_dialog import open_scope_dialog
from state_hub import hub as _state_hub
import audit_logic
from audit_logic import (
    is_commercial_form as _is_commercial_form,
    _latest_mtime,
    biz_days_since as _biz_days_since,
    check_forms, check_docusketch, check_photos, resolve_pics_dir,
    TECH_PATTERN, ABBREV, persist_key,
    para_is_struck,
    audit_jobs as _audit_jobs_core,
    detect_activity,
    detect_carrier_from_ems,
    find_docs_dir,
    DOCUSKETCH_RE,
)

_CFG       = config.load()
RUNS_DIR   = _CFG["runs_dir"]
AUDIT_BASE = _CFG["audit_base"]
# Workcenter URL — shown as a clickable link next to missing forms (and
# next to missing photos when Fernando is on the job, since he uploads
# direct to Workcenter rather than OneDrive). Empty string disables the
# link; user sets it in the settings dialog.
WORKCENTER_URL = (_CFG.get("workcenter_url") or "").strip()

# Run-doc parsing logic lives in the UI-free run_doc module, shared with the
# web panels. Re-export the names this module + its callers use so the Tk UI
# and external importers are unaffected. See EMS_Tk_Extraction_Plan.md.
from run_doc import (  # noqa: E402
    _RUN_DOC_DATE_RE_CACHE, _extract_date_from_folder_name,
    _parse_folder_date, _find_run_doc_for_date, _activity_labels_from_run_doc,
    _composed_folder_lookup, audit_jobs,
)
# PICS/unit resolution helpers — UI-free, in sp_enrich (shared with web).
from sp_enrich import (  # noqa: E402
    _PIC_EXTS, _resolve_pics_folder, _resolve_all_pics_folders,
    _STAGE_FOLDER_PATTERNS, _detect_done_stages,
    _unit_segment_from_pics_path, _unit_num_from_pics_path,
    _UNIT_NAME_STOPWORDS, _name_tokens_for_unit_match, _pick_default_pics_path,
)


def _job_uses_workcenter_for_photos(techs):
    """Fernando's photos live on Workcenter, not OneDrive — so when his name
    is on a job and a photo is flagged missing, point to Workcenter."""
    return any("fernando" in str(t).lower() or t.upper() == "FB"
               for t in (techs or []))


# Photo-row stage chip. The audit's missing-photo strings (`Demo pics`,
# `Mold Prep pics`, etc.) come from `audit_logic.check_photos`; this
# helper picks a short label + accent color so the audit panel can show
# WHICH stage of the job is short of photos at a glance instead of
# burying every variant in the same red row.
_PHOTO_STAGE_CHIPS = (
    # (substring matched in item_text.lower(), chip label, bg color)
    # "mold after" is the user-preferred label for the after-mold-prep
    # stage (audit_logic flags it as "Mold After pics"). Must match
    # BEFORE the generic "mold" rule so it doesn't degrade to a plain
    # MOLD chip.
    ("mold after",     "MOLDAFTER", "#8E44AD"),
    ("post mold prep", "MOLDAFTER", "#8E44AD"),
    ("mold prep",      "MOLDPREP",  "#8E44AD"),
    ("mold",           "MOLD",      "#27AE60"),
    ("demo",           "DEMO",      "#E67E22"),
    ("abatement",      "ABATE",     "#F39C12"),
    ("reinspect",      "REINSP",    "#4A90D9"),
    ("initial",        "INITIAL",   "#7F8C8D"),
    ("post",           "POST",      "#566573"),
)


def _photo_stage_chip(item_text):
    """Return (label, bg_color) for a photo-issue row, or None when the
    item isn't stage-tagged (form rows, dispute notes, aging banner)."""
    if not item_text:
        return None
    low = item_text.lower()
    for needle, label, color in _PHOTO_STAGE_CHIPS:
        if needle in low:
            return (label, color)
    return None


# Stage subfolder routing for WC photo imports. Maps the audit item text
# (e.g. "Initial pics", "Demo pics", "Mold After pics") to the stage
# subfolder name we want under PICS. Order matters — "mold after" /
# "post mold prep" must match before "mold prep" before "mold".
# `audit_logic.check_photos` matches these folders by case-insensitive
# keyword substring, so title-casing here is purely cosmetic.
#
# The audit's "Mold After pics" label (2026-05-18 rename) routes to
# the same physical subfolder as "Post Mold Prep" so the legacy folder
# name still works — the audit accepts any of `Post Mold Prep`,
# bare `Post Mold`, or `Mold After` for that stage.
_STAGE_FOLDER_PATTERNS_FOR_IMPORT = (
    ("mold after",     "Mold After"),
    ("post mold prep", "Post Mold Prep"),
    ("mold prep",      "Mold Prep"),
    ("post mold",      "Post Mold"),
    ("mold",           "Mold"),
    ("demo",           "Demo"),
    ("abatement",      "Abatement"),
    ("reinspect",      "Reinspection"),
    ("initial",        "Initial"),
    ("post",           "Post"),
)


def _stage_folder_for_item(item_text):
    """Return the stage subfolder name (e.g. "Initial") for a photo
    import item, or None when the item isn't stage-tagged. Used by the
    WC import flow to drop photos into PICS/<stage>/ instead of the
    PICS root, so audits find them under the right keyword."""
    if not item_text:
        return None
    low = item_text.lower()
    for needle, folder in _STAGE_FOLDER_PATTERNS_FOR_IMPORT:
        if needle in low:
            return folder
    return None

# State persistence routes through the shared persistence module — one
# atomic write path, schema-validated. _load_state stays as a thin shim
# only because two existing call sites use the dict-style .get() form.
def _load_state():
    return persistence._load()

def _save_state(key, value):
    persistence.set_value(key, value)

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
UNIT_RE        = re.compile(
    r'(?:\bunit\b|\bapt\b\.?|\bsuite\b|(?<![\w])#)\s*#?\s*([\w]{1,5})(?!\w)',
    re.IGNORECASE)
# SharePoint web-download zip name format — e.g. OneDrive_2026-04-28.zip
ONEDRIVE_RE    = re.compile(r'OneDrive_\d{4}-\d{2}-\d{2}.*\.zip$', re.IGNORECASE)
# Workcenter export-filename patterns now live in wc_zip_import (their
# natural home — find_wc_zips consumes them). Re-exported here so this
# module's WC import flow + snapshot_gui (which imports them from here)
# are unaffected. See EMS_Tk_Extraction_Plan.md.
from wc_zip_import import WC_DOCUMENTS_RE, WC_ATTACHMENTS_RE  # noqa: E402
WC_MULTIPART_RE   = re.compile(
    r'^(?P<base>.+?)-part-(?P<n>\d+)-of-(?P<m>\d+)\.zip$', re.IGNORECASE)


def _group_wc_zips(filenames, downloads_dir):
    """Collapse multi-part zip sets into single groups.

    Input: filenames already filtered to a WC zip pattern, sorted
    newest-mtime first. Output: list of (label, [absolute_paths])
    tuples in the same newest-first order — multi-part siblings
    collapsed onto the most-recent member's slot. Single zips become
    a 1-element group."""
    groups = []
    seen_keys = set()
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
DOWNLOADS      = os.path.join(os.environ["USERPROFILE"], "Downloads")

# Image / video extensions for the photo-count probe in audit results
# _PIC_EXTS + the PICS-resolution helpers (_resolve_pics_folder,
# _resolve_all_pics_folders, _STAGE_FOLDER_PATTERNS, _detect_done_stages)
# now live in sp_enrich, re-exported via the shim import above.


def _ask_unit_for_import(parent, unit_list, *, kind="photos",
                          client_name=""):
    """Modal unit picker for WC zip imports on multi-unit properties.

    Returns the chosen unit path, or "" for "extract to property root
    (use the default PICS routing)", or None when the user cancels
    (caller should abort the import).

    `kind` is a short noun like "photos" / "forms" used in the prompt
    so the dialog text matches the import flow."""
    dlg = tk.Toplevel(parent)
    dlg.title("Pick unit")
    dlg.resizable(False, False)
    dlg.grab_set()
    wf = tk.Frame(dlg, bg=BG, padx=18, pady=14)
    wf.pack()
    title_txt = (f"This is a multi-unit property — which unit do these "
                 f"{kind} belong to?")
    if client_name:
        title_txt += f"\n\n{client_name}"
    tk.Label(wf, text=title_txt, font=("Segoe UI Variable", 10, "bold"),
             bg=BG, fg=TEXT_DARK, justify="left", wraplength=420
             ).pack(anchor="w", pady=(0, 8))
    pick_var = tk.IntVar(value=0)
    # 0 = "Property root (default PICS)"; 1..N = unit_list[i-1].
    tk.Radiobutton(
        wf, text="Property root  (use default PICS)",
        variable=pick_var, value=0,
        font=("Segoe UI Variable", 9), bg=BG, activebackground=BG,
        anchor="w"
    ).pack(anchor="w", pady=1)
    for idx, u in enumerate(unit_list, start=1):
        # Show the full relative path so nested layouts (Villaigo /
        # Unit 101) read unambiguously.
        rel = u.get("rel") or u["name"]
        rel_disp = rel.replace(os.sep, " / ").replace("/", " / ")
        tk.Radiobutton(
            wf, text=rel_disp, variable=pick_var, value=idx,
            font=("Segoe UI Variable", 9), bg=BG, activebackground=BG,
            anchor="w", justify="left", wraplength=400
        ).pack(anchor="w", pady=1)
    result = [None]
    def _ok():
        idx = pick_var.get()
        if idx == 0:
            result[0] = ""
        else:
            try:
                result[0] = unit_list[idx - 1]["path"]
            except (IndexError, KeyError):
                result[0] = ""
        dlg.destroy()
    def _cancel():
        result[0] = None
        dlg.destroy()
    br = tk.Frame(wf, bg=BG); br.pack(fill="x", pady=(10, 0))
    tk.Button(br, text="Cancel", font=("Segoe UI Variable", 9),
              bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
              padx=12, pady=4, command=_cancel
              ).pack(side="left")
    tk.Button(br, text="Import",
              font=("Segoe UI Variable", 9, "bold"),
              bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
              relief="flat", padx=12, pady=4, command=_ok
              ).pack(side="right")
    dlg.wait_window()
    return result[0]


# The unit helpers (_unit_segment_from_pics_path, _unit_num_from_pics_path,
# _UNIT_NAME_STOPWORDS, _name_tokens_for_unit_match, _pick_default_pics_path)
# now live in sp_enrich, re-exported via the shim import above.


# _extract_date_from_folder_name + _RUN_DOC_DATE_RE_CACHE now live in run_doc
# (re-exported via the shim import above).


def _trash_imported_zips(paths):
    """Local alias for wc_zip_import.trash_imported_zips — see that
    function for the contract. Kept as a thin wrapper so the existing
    call sites in this file don't need to change."""
    try:
        from wc_zip_import import trash_imported_zips as _t
        _t(paths)
    except Exception:
        pass


# (date_iso, client_canon) -> "Activity — Tech1 / Tech2" or "" when no
# match. Populated by _activity_from_run_doc, cleared per process.
_SP_ROW_ACTIVITY_CACHE: dict[tuple, str] = {}


# _parse_folder_date + _activity_labels_from_run_doc now live in run_doc
# (re-exported via the shim import above).


def _activity_from_run_doc(folder_date_str, client_name):
    """For an SP match's folder_date + the audit row's client name,
    look up the day's run-doc and return a short activity summary like
    'Mitigation — Mark E' that the SP dialog renders on a sub-line.

    Returns "" when:
      - folder_date doesn't parse,
      - no run-doc exists for that date,
      - the run-doc has no matching client row.

    Cached by (date_iso, client_canon) so multiple SP folders for the
    same day+client only parse the run-doc once."""
    if not folder_date_str or not client_name:
        return ""
    d = _parse_folder_date(folder_date_str)
    if not d:
        return ""
    canon = re.sub(r"\s+", " ", (client_name or "").strip().lower())
    key = (d.isoformat(), canon)
    if key in _SP_ROW_ACTIVITY_CACHE:
        return _SP_ROW_ACTIVITY_CACHE[key]

    summary = ""
    try:
        doc_path = _find_run_doc_for_date(d)
    except Exception:
        doc_path = None
    if doc_path:
        try:
            from state_hub import hub as _hub
            jobs, _date = _hub.parse_run_doc(doc_path)
        except Exception:
            jobs = []
        # Pick the matching job — exact lowercase first, then
        # contains-either-way fallback so "Smith, John" matches
        # "Smith, John A" / vice versa.
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
        if matched is not None:
            try:
                info = detect_activity(
                    matched.get("raw") or "",
                    section=matched.get("section"),
                    new_loss=matched.get("new_loss"))
                labels = info.get("labels") or []
            except Exception:
                labels = []
            activity = ", ".join(labels) if labels else "Unspecified"
            techs = matched.get("techs") or []
            tech_part = (" — " + " / ".join(techs)) if techs else ""
            summary = f"{activity}{tech_part}"
    _SP_ROW_ACTIVITY_CACHE[key] = summary
    return summary


# _find_run_doc_for_date now lives in run_doc (re-exported via the shim above).


# Stage subfolder detection lives in stages.py — `_detect_stage_subfolder`
# is kept as a thin alias so the rest of this module reads the same.
_detect_stage_subfolder = stages.detect_sp_folder_subfolder


def _sp_folder_tag(sp_folder_name, client):
    """Strip the client name (and stray date tokens) from a SharePoint
    folder name to recover any identifying tag like 'EQ pics', 'Initial',
    'Demo'. The lead techs sometimes file equipment shots into a separate
    sub-folder per client, and we want that tag to survive the rename so
    the .jpg's purpose stays obvious in OD.

    Returns '' if nothing distinguishing remains.
    """
    if not sp_folder_name:
        return ""
    name = sp_folder_name.strip()
    full = " ".join((client or "").lower().split())
    if "," in (client or ""):
        last = client.split(",", 1)[0].strip().lower()
    else:
        parts = (client or "").split()
        last = parts[-1].lower() if parts else ""
    # Case-insensitive removal of full or last name
    for needle in [full, last]:
        if not needle:
            continue
        nl = name.lower()
        idx = nl.find(needle)
        if idx >= 0:
            name = name[:idx] + name[idx + len(needle):]
    # Strip date-like prefixes/suffixes (4-23-26, 4/23/2026, etc.)
    name = re.sub(r'^\s*\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\s*', "", name)
    name = re.sub(r'\s*\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\s*$', "", name)
    # Strip leading/trailing separators
    name = re.sub(r'^[\s\-_,.]+|[\s\-_,.]+$', "", name)
    # Collapse internal whitespace runs
    name = re.sub(r'\s+', " ", name).strip()
    return name


# SharePoint-import manifest helpers + enrich_with_sharepoint now live in the
# UI-free sp_enrich module (shared with the web panels). Re-export the names
# this module + its callers (web uses _append_sp_manifest_originals and
# enrich_with_sharepoint) use so the Tk UI and external importers are
# unaffected. See EMS_Tk_Extraction_Plan.md.
from sp_enrich import (  # noqa: E402
    _SP_MANIFEST, _SP_MANIFEST_TTL_DAYS, _SP_MANIFEST_DIR,
    _sp_manifest_key, _sp_manifest_path, _legacy_sp_manifest_path,
    _migrate_legacy_sp_manifest, _read_sp_manifest,
    _read_sp_manifest_originals, _append_sp_manifest_originals,
    _clear_sp_manifest, enrich_with_sharepoint,
)


# ── Doc parsing ───────────────────────────────────────────────────────────────

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
        for m in TECH_PATTERN.finditer(clean):
            resolved = ABBREV.get(m.group(0).upper(), m.group(0).title())
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


def _expand_multi_pinned_jobs(jobs, run_date):
    """Replicate any job whose run-day pin list has ≥ 2 paths.

    For a single-pin or no-pin job: returns the job unchanged.
    For a multi-pin job (e.g. "Avila Apartments" pinned to Unit 527 +
    Unit 1416): returns 2 jobs, each with `client` suffixed by the
    unit folder name and the resolved path side-channeled in a lookup
    map keyed by augmented client name.

    Returns (expanded_jobs, {augmented_client: path}).
    """
    if not jobs or not run_date:
        return list(jobs), {}
    out_jobs = []
    lookup_map = {}
    for j in jobs:
        client = (j.get("client") or "").strip()
        if not client:
            out_jobs.append(j)
            continue
        try:
            paths = persistence.get_run_day_units(run_date, client)
        except Exception:
            paths = []
        if len(paths) <= 1:
            out_jobs.append(j)
            continue
        for path in paths:
            unit_name = os.path.basename(path.rstrip("\\/")) or path
            new_j = dict(j)
            new_j["client"] = f"{client} — {unit_name}"
            new_j["_expanded_from"] = client
            new_j["_expanded_unit_path"] = path
            out_jobs.append(new_j)
            lookup_map[new_j["client"]] = path
    return out_jobs, lookup_map


# _composed_folder_lookup + audit_jobs (the thin AUDIT_BASE/lookup wrapper
# over audit_logic.audit_jobs) now live in run_doc, re-exported via the shim
# import above.


# ── GUI ───────────────────────────────────────────────────────────────────────

_ICON = paths.resource("wrench.ico")

class RunAuditApp(ToolPanel):
    TOOL_TITLE = "Audit"
    TOOL_AUMID = "Servpro.EMS.Audit"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Audit")
        self.geometry("640x600")
        self.configure(bg=BG)
        self.resizable(True, True)
        if os.path.isfile(_ICON):
            try:
                self.iconbitmap(_ICON)
            except Exception:
                pass

        self.jobs         = []
        self.run_date     = ""
        self.doc_path     = tk.StringVar()
        self._last_results = None
        # Card frame per client — populated by `_render_one_card` on every
        # batch / streaming render. Used by `_refresh_single_card` to
        # locate the old card, destroy it, and drop a freshly-audited one
        # back into the same scroll position. Without this map a single
        # Find-Folder click would have to re-render the whole audit.
        self._card_by_client: dict[str, tk.Frame] = {}
        # Closure ref to `_render._render_one_card` so post-render
        # callers can rebuild one card without re-running `_render`.
        self._render_one_card_fn = None
        self._pending_render = None  # (results, err) stashed when panel hidden
        # Streaming-render buffer: results accumulate here when the
        # panel is hidden during a streaming audit. Drained one card
        # at a time at a paced rate when the panel becomes visible
        # so the user sees cards animate in instead of all at once.
        self._streaming_buffer = []
        self._streaming_drain_pending = False
        # Audit-run epoch — incremented at the top of every _run_audit
        # / audit_single_client call. The worker thread captures this
        # at launch; every `self.after(0, ...)` enqueue checks the
        # current value before painting. Stops orphan cards from a
        # prior run (whose worker is still draining its result list)
        # from leaking into a freshly-cleared _inner — the duplicate-
        # cards bug the user reported after re-running audits.
        self._audit_run_epoch = 0
        # Tracks the last audit kind so the "↺ Run Audit" button +
        # per-card refresh fallbacks (force-sync, Find Folder, Change
        # Folder) re-run THE VIEW THE USER IS ON, not always the
        # daily-run audit. ('daily', None) = the run-doc sweep;
        # ('single', '<client>') = single-job audit via Audit One Job
        # / audit_single_client / Pin-&-Audit. Toggle via
        # `_set_last_audit_kind`; rerun via `_rerun_current_audit`.
        self._last_audit_kind: tuple[str, str | None] = ("daily", None)

        # Tab state — the audit panel hosts four views:
        #   'run'      — daily-run audit (default)
        #   'initial'  — Trello-driven Initial Upload queue
        #   'backlog'  — historical audit results (was its own launcher tool)
        #   'sprecent' — SharePoint folders changed in last N days
        # All views except 'run' are built lazily on first switch so
        # users who never click their tab don't pay the load cost on
        # launch (Trello round-trip, SP walk, etc.).
        self._mode = "run"
        self._initial_view = None
        self._backlog_view = None
        self._sprecent_view = None

        self._build_ui()
        self._restore_last_doc()

    def on_show(self):
        # Drain any audit result that finished while we were hidden
        if self._pending_render is not None:
            results, err = self._pending_render
            self._pending_render = None
            self._render(results, err)
        # If a streaming audit ran (or is still running) while hidden,
        # cards are sitting in the buffer waiting for paced render.
        # Kick the drain so the user sees them animate in rather
        # than appear all at once when the panel maps.
        if self._streaming_buffer and not self._streaming_drain_pending:
            self._streaming_drain_pending = True
            self.after(0, self._streaming_drain_tick)

    # Pixels-per-card pacing for the buffer drain. 25 ms ≈ 40 fps —
    # each card visibly lands separately without dragging the wait.
    _STREAM_DRAIN_INTERVAL_MS = 25

    def _streaming_enqueue(self, r, *, epoch=None):
        """Card-arrival hook called from the worker thread (via
        self.after(0, ...)). When the panel is visible we paint
        immediately so the manual re-run case keeps its as-fast-as-
        the-worker streaming feel. When hidden we buffer the result
        for paced drain on on_show.

        Epoch gate: callers pass `epoch=my_epoch` and we bail if a
        newer audit run has bumped `_audit_run_epoch`. Prevents
        stale-run cards from leaking into the freshly-cleared _inner
        after the user re-runs the audit.
        """
        if epoch is not None and self._audit_run_epoch != epoch:
            return
        try:
            mapped = bool(self.winfo_ismapped())
        except tk.TclError:
            mapped = False
        if mapped:
            try:
                self._streaming_render_one(r)
            except Exception:
                pass
            return
        self._streaming_buffer.append(r)

    def _streaming_drain_tick(self):
        """Render one buffered card and reschedule. Stops when the
        buffer empties or the panel is hidden (next on_show will
        resume)."""
        self._streaming_drain_pending = False
        try:
            mapped = bool(self.winfo_ismapped())
        except tk.TclError:
            mapped = False
        if not mapped or not self._streaming_buffer:
            return
        r = self._streaming_buffer.pop(0)
        try:
            self._streaming_render_one(r)
        except Exception:
            pass
        if self._streaming_buffer:
            self._streaming_drain_pending = True
            self.after(self._STREAM_DRAIN_INTERVAL_MS,
                       self._streaming_drain_tick)

    def _build_ui(self):
        self.build_header("SERVPRO  ·  Audit",
                          subtitle="Daily Run + Initial Upload Queue",
                          pady=14)

        # Tab strip — picks the body. Lives on `self` (above the body
        # frames) so it's always visible. Active tab gets the green
        # fill; inactive gets a soft grey-green.
        self._build_tab_strip()

        # Tab body containers — empty Frames per tab, populated lazily
        # on first switch. Only one is packed at a time.
        self._initial_body  = tk.Frame(self, bg=BG)
        self._backlog_body  = tk.Frame(self, bg=BG)
        self._sprecent_body = tk.Frame(self, bg=BG)

        # Daily Run body — wraps the existing audit chrome so we can
        # show/hide the whole pane via pack/pack_forget. Every widget
        # that used to parent to `self` now parents to `self._run_body`
        # so the Initial body can take its place when the tab switches.
        self._run_body = tk.Frame(self, bg=BG)
        self._run_body.pack(fill="both", expand=True)

        # File picker + section checkboxes — responsive: one row when the
        # window is wide, two rows (file picker on top, sections below)
        # when narrow. The sections "snap" to the right of the file picker
        # at ~720px and back below it when shrunk.
        self._top_row = tk.Frame(self._run_body, bg=BG, padx=20, pady=12)
        self._top_row.pack(fill="x")

        self._fp_inner = tk.Frame(self._top_row, bg=BG)
        self._fp_inner.pack(side="left", anchor="w")
        ctkh.h2(self._fp_inner, "Daily Run (.docx)").grid(
            row=0, column=0, sticky="w")
        ctkh.entry(self._fp_inner, textvariable=self.doc_path,
                   width=360).grid(row=0, column=1, padx=8)
        ctkh.btn(self._fp_inner, "Browse", command=self._browse,
                 kind="primary", width=80
                 ).grid(row=0, column=2)
        # 📄 Open — opens the currently-loaded run-doc in Word so the
        # user can read/edit it without navigating to the Daily Run
        # folder in Explorer. Falls back to today's run-doc when
        # nothing is loaded yet (shaves a Browse for the morning case).
        ctkh.btn(self._fp_inner, "📄 Open",
                 command=self._open_loaded_run_doc,
                 kind="ghost", width=90
                 ).grid(row=0, column=3, padx=(6, 0))
        # ⏪ / 📅 / ⏭  — icon-only trio. ⏪ walks one day back from the
        # current view, ⏭ one day forward, 📅 resets the cursor to
        # today. Tooltips spell out the action on hover.
        _back_btn = ctkh.btn(self._fp_inner, "⏪",
                             command=self._load_yesterday_run_doc,
                             kind="ghost", width=44)
        _back_btn.grid(row=0, column=4, padx=(4, 0))
        attach_tooltip(_back_btn, "Walk one day back (skips empty days)")

        _today_btn = ctkh.btn(self._fp_inner, "📅 Today",
                              command=self._load_today_run_doc,
                              kind="ghost", width=90)
        _today_btn.grid(row=0, column=5, padx=(4, 0))
        attach_tooltip(_today_btn, "Reset the cursor and load today's run-doc")

        _fwd_btn = ctkh.btn(self._fp_inner, "⏭",
                            command=self._load_tomorrow_run_doc,
                            kind="ghost", width=44)
        _fwd_btn.grid(row=0, column=6, padx=(4, 0))
        attach_tooltip(_fwd_btn, "Walk one day forward (skips empty days)")

        # SharePoint month-archive lives in the ⋯ More menu now (rare
        # action — once-a-month house-keeping). Kept off the top row
        # so the file picker doesn't compete for visual attention.

        # Section checkboxes — sec_inner is the actual content; sec_row is
        # the "narrow mode" home that holds it when there's no room beside
        # the file picker. Note: sec_inner's parent is `self._run_body`,
        # NOT sec_row, so ResponsiveSnap can re-pack it into top_row via
        # in_=. Tk only allows pack(in_=X) when X is the slave's parent
        # OR a descendant of it; making the parent `self._run_body` lets
        # us swap between any of run_body's descendant frames.
        self._sec_row = tk.Frame(self._run_body, bg=BG, padx=20, pady=4)
        self._sec_inner = tk.Frame(self._run_body, bg=BG)
        self._sec_inner.pack(in_=self._sec_row, side="left", anchor="w")
        ctkh.h2(self._sec_inner, "Sections to audit").pack(side="left")
        self.var_work    = tk.BooleanVar(value=True)
        self.var_monitor = tk.BooleanVar(value=True)
        ctkh.ctk.CTkCheckBox(self._sec_inner, text="Work to Be Performed",
                             variable=self.var_work, font=ctkh.font(10),
                             text_color=TEXT_DARK,
                             fg_color=GREEN, hover_color=GREEN_DARK,
                             border_color=BORDER, corner_radius=4,
                             checkbox_height=18, checkbox_width=18
                             ).pack(side="left", padx=(14, 0))
        ctkh.ctk.CTkCheckBox(self._sec_inner, text="Monitor",
                             variable=self.var_monitor, font=ctkh.font(10),
                             text_color=TEXT_DARK,
                             fg_color=GREEN, hover_color=GREEN_DARK,
                             border_color=BORDER, corner_radius=4,
                             checkbox_height=18, checkbox_width=18
                             ).pack(side="left", padx=(10, 0))
        self._sec_row.pack(fill="x")  # default: own row (narrow layout)

        # Results area
        self.status_label = ctkh.ctk.CTkLabel(
            self._run_body, text="Load a run document to begin.",
            font=ctkh.font(10), text_color=TEXT_GRAY, fg_color=BG)
        self.status_label.pack(anchor="w", padx=20, pady=(6, 2))

        # Responsive snap — sections jump to the right of the file picker
        # once the window has room for both, and back below when shrunk.
        ResponsiveSnap(self._run_body,
                       inline_parent=self._top_row,
                       narrow_parent=self._sec_row,
                       movable=self._sec_inner,
                       narrow_before=self.status_label)

        # Bottom bar — packed BEFORE the scrollable body and anchored to
        # the bottom so action buttons stay visible even when the window
        # is short. Buttons are added below.
        bar = ResponsiveActionBar(self._run_body, root_widget=self,
                                  bg=BG, padx=20, pady=10)
        bar.pack(side="bottom", fill="x")

        scroll = ScrollableFrame(self._run_body, bg=BG, padx=10)
        scroll.pack(fill="both", expand=True)
        self._canvas = scroll.canvas
        self._inner  = scroll.inner
        self._scroll = scroll
        # Card-body virtualization: keeps only viewport-overlapping
        # bodies fully built, dramatically reducing the live HWND
        # count Tk has to reposition during scroll. Bodies of cards
        # outside the overscan band have their children destroyed
        # and the body Frame frozen at its last known height; on
        # scroll-back-in, the registered build_fn rebuilds them.
        self._virt_cards = VirtualizedCardList(scroll, overscan_px=800)

        # Action bar — only the two daily-loop actions stay visible.
        # Photo Folders nav, Export PDF, and Archive Month moved into
        # the ⋯ More overflow menu so the bar is focused.
        # Routes through `_rerun_current_audit` so clicking from inside
        # a single-job view re-runs THAT job, not the full daily sweep
        # (used to silently swap the user's context out from under
        # them, especially after a force-sync where they wanted to
        # verify the pull on the same row).
        run_btn = ctkh.btn(bar, "↺  Run Audit",
                           command=self._rerun_current_audit,
                           kind="primary", width=150, height=36)
        bar.add(run_btn, group="primary", side="right", padx=(0, 0))
        # Single-job audit — bypasses the run doc. Spot-check one
        # insured by name without re-running the full daily sweep.
        single_btn = ctkh.btn(
            bar, "🔍 Audit One Job", command=self._audit_one_job,
            kind="primary", width=160, height=36,
            fg_color="#7B5BA8", hover_color="#5C4081")
        bar.add(single_btn, group="secondary", side="right", padx=(0, 8))

        # ⋯ More — overflow menu for rare actions. The toolstrip already
        # has a Photo Folders button, so a duplicate entry here was
        # noise; keep this menu focused on actions you can't get at
        # from the main chrome.
        more = ctkh.MoreMenu(bar, label="⋯ More", width=100)
        more.add("Export flagged jobs to PDF", icon="📄",
                 command=self._export_pdf)
        more.add("Push new losses → APA Initial Uploads", icon="📤",
                 command=self._push_new_losses_to_apa)
        more.add("🔁 Post daily misses → Trello", icon="📋",
                 command=self._post_daily_misses_to_trello)
        more.add("Escalation contacts…", icon="✉",
                 command=self._open_escalation_contacts_dialog)
        more.add("Copy XA apology note", icon="🔔",
                 command=self._copy_xa_apology_note)
        more.add_separator()
        more.add("Archive month on SharePoint…", icon="🗓",
                 command=self._archive_month_dialog)
        bar.add(more.button, group="secondary", side="right", padx=(0, 8))
        # _export_btn was an enable/disable handle elsewhere — keep the
        # attribute alive so existing code that toggles its state doesn't
        # crash. Point at the More button so a disabled export grays the
        # whole menu (acceptable: nothing else in the menu needs the
        # results-loaded preconditions).
        self._export_btn = more.button

    # ── Tab strip + body switching ──────────────────────────────────────
    # Tabs are described declaratively here so adding a fifth tab later
    # (or renaming/icon-swapping) is a one-line change. Each entry:
    #   key           — internal mode id (matches `self._mode`)
    #   label         — button text including emoji
    #   show_method   — method to call when the tab is clicked
    # NOTE: the "Initial Upload" tab was retired (2026-07-22) — the
    # standalone IUQ tool was removed. The InitialUploadView class remains
    # in initial_upload_queue.py as a shared library (Snapshot / APA /
    # snapshots_excel still import helpers from it), just no longer surfaced
    # as an Audit tab.
    _TAB_DEFS = (
        ("run",      "🔎 Daily Run",      "_show_run"),
        ("backlog",  "📋 Backlog",        "_show_backlog"),
        ("sprecent", "🗂 SP Recent",      "_show_sprecent"),
    )

    def _build_tab_strip(self):
        """The thin row of tab buttons under the header. Active tab gets
        the sage-green fill; inactive tabs use the elevated card surface
        so they sit one step above the panel background."""
        bar = tk.Frame(self, bg=BG, padx=14, pady=6)
        bar.pack(fill="x")
        self._tab_buttons = {}
        for i, (key, label, method_name) in enumerate(self._TAB_DEFS):
            cmd = getattr(self, method_name)
            btn = tk.Button(
                bar, text=label,
                font=("Segoe UI Variable", 10),
                bg=SURFACE_2, fg=TEXT_GRAY,
                activebackground=NEUTRAL_HOVER, activeforeground=TEXT_DARK,
                relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                command=cmd)
            btn.pack(side="left", padx=(0 if i == 0 else 4, 0))
            self._tab_buttons[key] = btn
        self._update_tab_styles()

    def _update_tab_styles(self):
        """Restyle the tab buttons after a mode change so the active
        one reads as visually selected."""
        for key, btn in self._tab_buttons.items():
            active = (key == self._mode)
            try:
                btn.config(
                    bg=GREEN_DARK if active else SURFACE_2,
                    fg=WHITE if active else TEXT_GRAY,
                    activebackground=GREEN_DARK if active else NEUTRAL_HOVER,
                    activeforeground=WHITE if active else TEXT_DARK,
                    font=("Segoe UI Variable", 10,
                          "bold" if active else "normal"))
            except tk.TclError:
                pass

    def _hide_all_bodies(self):
        for body in (self._run_body, self._initial_body,
                      self._backlog_body, self._sprecent_body):
            try:
                body.pack_forget()
            except tk.TclError:
                pass

    def _show_run(self):
        if self._mode == "run":
            return
        self._mode = "run"
        self._hide_all_bodies()
        try:
            self._run_body.pack(fill="both", expand=True)
        except tk.TclError:
            pass
        self._update_tab_styles()
        # Drain any audit results that completed while the Daily Run
        # body was hidden (user audited a job, then switched to a
        # sibling tab — Initial Upload, Backlog, SP Recent — before
        # the audit finished). Without this, _render() ran into an
        # unmapped body and the cards never appeared even after the
        # user switched back. ToolPanel.on_show only fires on the
        # outer launcher switch, not on audit-internal tab changes,
        # so we need this drain right where the body becomes visible.
        if self._pending_render is not None:
            results, err = self._pending_render
            self._pending_render = None
            try:
                self._render(results, err)
            except tk.TclError:
                pass

    def _show_backlog(self):
        if self._mode == "backlog":
            return
        self._mode = "backlog"
        self._hide_all_bodies()
        if self._backlog_view is None:
            try:
                from print_audit_gui import BacklogView
                self._backlog_view = BacklogView(self._backlog_body)
                self._backlog_view.pack(fill="both", expand=True)
            except Exception as ex:
                self._render_tab_error(self._backlog_body, "Backlog", ex)
        self._backlog_body.pack(fill="both", expand=True)
        self._update_tab_styles()

    def _show_sprecent(self):
        if self._mode == "sprecent":
            return
        self._mode = "sprecent"
        self._hide_all_bodies()
        if self._sprecent_view is None:
            try:
                from sp_recent_audit import SpRecentView
                self._sprecent_view = SpRecentView(self._sprecent_body)
                self._sprecent_view.pack(fill="both", expand=True)
            except Exception as ex:
                self._render_tab_error(self._sprecent_body,
                                        "SP Recent", ex)
        self._sprecent_body.pack(fill="both", expand=True)
        self._update_tab_styles()

    def _render_tab_error(self, body, tab_name, ex):
        """Friendly error placeholder so a failed lazy-load doesn't
        leave the user staring at an empty pane."""
        err = tk.Label(body,
                        text=(f"Couldn't load {tab_name} view:\n"
                              f"{ex}\n\nTry restarting the app."),
                        font=("Segoe UI Variable", 9, "italic"),
                        bg=BG, fg=FLAG_RED, padx=20, pady=20,
                        wraplength=560, justify="left")
        err.pack(fill="both", expand=True)

    def _open_loaded_run_doc(self):
        """Open the currently-loaded run-doc in Word (or whatever
        default handler the user has for .docx). When nothing is
        loaded, fall back to today's run-doc — the morning workflow.
        Surfaces a friendly error rather than a stack trace when the
        file simply doesn't exist yet."""
        path = (self.doc_path.get() or "").strip()
        if not path or not os.path.isfile(path):
            try:
                today_doc = _find_run_doc_for_date(datetime.today())
            except Exception:
                today_doc = None
            if today_doc and os.path.isfile(today_doc):
                path = today_doc
            else:
                messagebox.showinfo(
                    "No run doc loaded",
                    "Load a run document with Browse first, or place "
                    "today's run-doc in the Daily Run folder.")
                return
        try:
            os.startfile(path)
        except OSError as ex:
            messagebox.showerror("Couldn't open run doc",
                                 f"{path}\n\n{ex}")

    def _load_today_run_doc(self):
        """Reset the day cursor and load today's run-doc. After this,
        ⏪ walks back from today and ⏭ walks forward from today —
        regardless of where the user had wandered to before."""
        self._current_run_date = datetime.today()
        self._load_run_doc_for_offset(0, label="today")

    def _load_tomorrow_run_doc(self):
        """Walk one day forward from the date currently being viewed
        (not from today). Multiple clicks step further forward day-by-
        day. Symmetric to _load_yesterday_run_doc."""
        self._walk_to_run_doc(direction=+1, label="next")

    def _load_yesterday_run_doc(self):
        """Walk one day back from the date currently being viewed.

        Multiple clicks step further back, so on the 14th the first
        click lands on the 13th and the second click on the 12th.
        Today resets the cursor. Empty days (weekends, vacation) are
        skipped so we always land on a real run-doc; capped at 14 days
        per click."""
        self._walk_to_run_doc(direction=-1, label="prior")

    @staticmethod
    def _parse_run_date_to_datetime(run_date):
        """Best-effort: turn a run-doc's `run_date` (whatever shape the
        parser hands back — string, date, datetime, or None) into a
        plain `datetime`. Returns None when nothing usable can be
        inferred — caller falls back to today."""
        if run_date is None:
            return None
        if isinstance(run_date, datetime):
            return run_date
        # date subclass — promote to datetime.
        try:
            import datetime as _dt
            if isinstance(run_date, _dt.date):
                return datetime(run_date.year, run_date.month, run_date.day)
        except Exception:
            pass
        s = str(run_date).strip()
        if not s:
            return None
        for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y",
                     "%Y-%m-%d", "%m.%d.%y", "%m.%d.%Y"):
            try:
                return datetime.strptime(s, fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _walk_to_run_doc(self, *, direction, label):
        """Step day-by-day from `_current_run_date` (defaults to today
        if unset) in `direction` (±1). Loads the first run-doc found
        within 14 days. Updates `_current_run_date` on success so the
        next click continues stepping from there."""
        start = getattr(self, "_current_run_date", None) or datetime.today()
        for step in range(1, 15):
            try:
                target = start + timedelta(days=direction * step)
                path = _find_run_doc_for_date(target)
            except Exception:
                path = None
            if path and os.path.isfile(path):
                self._current_run_date = target
                if path == self.doc_path.get():
                    self._run_audit()
                    return
                self.doc_path.set(path)
                try:
                    _save_state("run_audit_last_doc", path)
                except Exception:
                    pass
                self._load_doc(path)
                return
        messagebox.showinfo(
            f"No {label} run doc",
            f"Couldn't find a {label} run-doc within 14 days of "
            f"{start.strftime('%m/%d/%y')}.\n\n"
            "Click 📅 Today to reset the cursor, or Browse to pick a "
            "specific day. (If today's doc was just added and you've "
            "walked past it, the cursor needs resetting.)")

    def _load_run_doc_for_offset(self, day_offset, *, label):
        """Shared helper for Today / Yesterday quick-load buttons.
        `day_offset` is added to `datetime.today()` (use 0 for today,
        -1 for yesterday). `label` is the noun for the missing-doc
        message ("today" / "yesterday")."""
        try:
            target = datetime.today() + timedelta(days=day_offset)
            path = _find_run_doc_for_date(target)
        except Exception:
            path = None
        if not path or not os.path.isfile(path):
            messagebox.showinfo(
                f"No run doc for {label}",
                f"Couldn't find {label}'s run-doc in the Daily Run "
                "folder.\n\nTry Browse to pick a different day.")
            return
        if path == self.doc_path.get():
            # Already loaded — re-run the audit so the user gets a
            # fresh sweep without having to swap docs first.
            self._run_audit()
            return
        self.doc_path.set(path)
        try:
            _save_state("run_audit_last_doc", path)
        except Exception:
            pass
        self._load_doc(path)

    def _restore_last_doc(self):
        # Picking order:
        #   1. Doc passed on the command line (launcher or another tool
        #      explicitly handed us a path) — always wins.
        #   2. TODAY's run-doc found in RUNS_DIR — so the launcher's
        #      preload kicks off today's audit automatically without
        #      the user having to re-open a doc each morning.
        #   3. Whatever doc was saved as last-opened from a prior session.
        # Falling through to (3) means re-opening late in the day still
        # recovers the previous session's view if today's doc isn't
        # filed yet (e.g., user is auditing yesterday's overflow).
        import sys as _sys
        last = None
        for arg in _sys.argv[1:]:
            if arg and os.path.isfile(arg):
                last = arg
                break
        if not last:
            try:
                today_doc = _find_run_doc_for_date(datetime.today())
            except Exception:
                today_doc = None
            if today_doc and os.path.isfile(today_doc):
                last = today_doc
        if not last:
            last = _load_state().get("run_audit_last_doc")
        self._load_doc(last)

    def _load_doc(self, path):
        if not path or not os.path.isfile(path):
            return
        self.doc_path.set(path)
        self.show_loading(f"Reading {os.path.basename(path)}…")

        def _bg():
            try:
                jobs, run_date = _state_hub.parse_run_doc(path)
                err = None
            except Exception as ex:
                jobs, run_date, err = None, None, ex

            def _done():
                if err:
                    self.hide_loading()
                    return
                # Empty parse result — silently bail. Hits during the
                # auto-restore path when today's run-doc was created
                # but not yet filled in; no point popping the
                # "No Jobs" messagebox before the user has even
                # interacted with the panel.
                if not jobs:
                    self.hide_loading()
                    self.status_label.configure(
                        text="Run document parsed empty — "
                             "load a doc to begin.")
                    return
                self.jobs = jobs
                self.run_date = run_date
                # Keep the day-cursor in sync with whatever doc is now
                # on screen — `_walk_to_run_doc` reads
                # `self._current_run_date` as the anchor for ⏪/⏭, and
                # without this update the cursor drifts when the user
                # gets here via Browse / auto-restore / panel-swap
                # (only the 📅/⏪/⏭ buttons used to update it).
                try:
                    parsed_dt = self._parse_run_date_to_datetime(run_date)
                    if parsed_dt is not None:
                        self._current_run_date = parsed_dt
                except Exception:
                    pass
                # Run date + job count surface in the status_label below
                # once _run_audit completes; no separate date label needed.
                # _run_audit() will swap the spinner message to "Auditing N jobs…"
                self._run_audit()
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def consume_cli_args(self, cli_args):
        """Called by the launcher when another tool navigates here with
        context. Accepts:
          • a filesystem path → load that run doc
          • `audit:<insured>` → run a single-job audit on `<insured>`
            (used by Snapshot's "Audit Only" button so the snapshot
            panel stops carrying its own audit pipeline)."""
        for arg in cli_args:
            if isinstance(arg, str) and arg.startswith("audit:"):
                name = arg[len("audit:"):].strip()
                if name:
                    # Bypass the dialog — name is already chosen.
                    self._audit_named_jobs([name],
                                            source_label="snapshot")
                return
            if arg and os.path.isfile(arg):
                if arg != self.doc_path.get():
                    self._load_doc(arg)
                return

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Daily Run",
            filetypes=[("Word Documents", "*.docx"), ("All Files", "*.*")],
            initialdir=RUNS_DIR,
        )
        if not path:
            return
        self.doc_path.set(path)
        _save_state("run_audit_last_doc", path)
        self.show_loading(f"Reading {os.path.basename(path)}…")

        def _bg():
            try:
                jobs, run_date = _state_hub.parse_run_doc(path)
                err = None
            except Exception as ex:
                jobs, run_date, err = None, None, ex

            def _done():
                if err:
                    self.hide_loading()
                    messagebox.showerror("Error reading file", str(err))
                    return
                self.jobs = jobs
                self.run_date = run_date
                self._run_audit()
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _rerun_current_audit(self):
        """Re-run whichever audit the user is currently viewing.

        Wired to the "↺ Run Audit" toolstrip button so clicking it
        from inside a single-job view does NOT silently swap to the
        daily-run sweep (the user lost their context every time —
        especially noticeable after a force-sync where they want
        to verify the SP→OD pull worked on the same row).

        Also called by `_refresh_single_card` when its per-card
        closure isn't available, so the fallback path respects the
        current view too."""
        kind, target = self._last_audit_kind
        if kind == "single" and (target or "").strip():
            try:
                self.audit_single_client(target.strip())
                return
            except Exception:
                # If the single-job rerun explodes, fall through to
                # the daily-run path rather than leaving the user
                # staring at a frozen panel.
                pass
        self._run_audit()

    def _set_last_audit_kind(self, kind: str, target: str | None = None):
        """Persist the audit-mode marker. Called at the top of every
        audit kickoff so the rerun dispatcher always knows where to
        route."""
        self._last_audit_kind = (kind, target)

    def _run_audit(self):
        if not self.jobs:
            messagebox.showerror("No Jobs", "Load a run document first.")
            return

        selected = set()
        if self.var_work.get():    selected.add("work")
        if self.var_monitor.get(): selected.add("monitor")
        if not selected:
            messagebox.showerror("No Section", "Select at least one section to audit.")
            return
        # Mark daily-mode only after validation passes — otherwise a
        # cancelled "no jobs loaded" / "no section" click would flip
        # the rerun dispatcher away from a prior single-job view.
        self._set_last_audit_kind("daily")

        names = [j for j in self.jobs if j["section"] in selected]

        # Multi-unit expansion. When the user has day-pinned ≥ 2 unit
        # subfolders to a single row (via the 🏠 unit picker), explode
        # that one run-doc job into N child jobs — one per pinned unit
        # — each tagged with a unique client suffix so the audit
        # renders distinct rows. The expansion lookup overrides the
        # composed folder lookup chain (base wins) so each child
        # resolves to its specific unit folder.
        run_date_for_expand = self.run_date or datetime.today().strftime("%m-%d-%Y")
        expanded_names, expanded_lookup_map = _expand_multi_pinned_jobs(
            names, run_date_for_expand)
        names = expanded_names
        self._expanded_unit_lookup = expanded_lookup_map

        # Bump the epoch BEFORE the clear so any in-flight enqueues
        # from a prior run see a stale epoch and skip painting.
        self._audit_run_epoch += 1
        my_epoch = self._audit_run_epoch
        self._virt_cards.clear()
        self._card_by_client.clear()
        for w in self._inner.winfo_children():
            w.destroy()
        # Snap the canvas back to the top so a freshly-loaded audit starts
        # at row 1. Without this reset, Tk preserves the canvas's fractional
        # yview (e.g. 0.7 if the user was 70% down the prior list), and
        # when the new — possibly shorter — content lands, that fraction
        # maps to near the bottom of the new total, making it look like
        # there are still rows below where there aren't.
        self.update_idletasks()
        try:
            self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        run_date = self.run_date
        total = len(names)

        # ── Always-streaming render ───────────────────────────────────
        # Tk widget creation works on un-mapped frames — we just don't
        # see anything until the panel is shown. So we render chrome +
        # cards into self._inner regardless of visibility. When the
        # user finally clicks into Run Audit, they see whatever has
        # been streamed so far (paced via the drain buffer if the
        # audit completed while hidden), with the status line
        # counting up.
        #
        # No throbber: the status line "Auditing X / N…" is the
        # progress signal, and it lives on the panel itself rather
        # than blocking the whole panel behind a "loading tool" overlay
        # the way the previous batch path did.
        self.hide_loading()
        # Reset buffer state for the new audit run.
        self._streaming_buffer = []
        self._streaming_drain_pending = False
        self._render([], None, expected_total=total, streaming=True)
        self.status_label.configure(text=f"Auditing 0 / {total}…")

        def _thread():
            # Single batched audit_jobs call — builds the year-folder
            # listing on the network share ONCE. (An earlier per-job
            # streaming attempt called audit_jobs([nd], ...) in a loop,
            # which re-listdir'd the year folder per job and locked the
            # UI for ~1s per job on a slow share. One batch + per-
            # result UI streaming gives the same "cards fill in" feel
            # without the network amplification.)
            try:
                results, err = audit_jobs(
                    names, run_date=run_date,
                    expand_map=getattr(self, "_expanded_unit_lookup",
                                       None))
            except Exception as ex:
                results, err = None, str(ex)
            if not results:
                def _empty():
                    if err:
                        self.status_label.configure(
                            text=f"Error: {err}")
                    else:
                        self.status_label.configure(
                            text=f"No jobs to audit.")
                self.after(0, _empty)
                return

            # SP folder index built ONCE — same approach the old
            # batch path used. Then enrich + stream cards one by one.
            try:
                from sharepoint import build_sharepoint_folder_index
                folder_index = build_sharepoint_folder_index()
            except Exception:
                folder_index = None
            match_cache = {}

            for r in results:
                # If a newer audit run has started, abandon this one —
                # the user clicked Run Audit again and we'd otherwise
                # stream stale cards into their fresh _inner.
                if self._audit_run_epoch != my_epoch:
                    return
                try:
                    enrich_with_sharepoint(
                        r, run_date,
                        folder_index=folder_index,
                        match_cache=match_cache)
                except Exception:
                    pass
                # Route through _streaming_enqueue so cards either
                # paint immediately (visible panel) or buffer for
                # paced drain (hidden — user hasn't navigated yet).
                self.after(
                    0,
                    lambda r=r, ep=my_epoch:
                    self._streaming_enqueue(r, epoch=ep))

            def _finalize(ep=my_epoch):
                if self._audit_run_epoch != ep:
                    return
                self._last_results = results
                try:
                    audit_export.write_audit_md(
                        results,
                        run_date=self.run_date,
                        source="Run Audit")
                except Exception:
                    pass
                try:
                    self._render_status_after_stream()
                except Exception:
                    pass
            self.after(0, _finalize)

        threading.Thread(target=_thread, daemon=True).start()

    def _render_status_after_stream(self):
        """Re-paint the status line after the streaming worker fires
        its final card, so 'X jobs · Y flagged · Z OK' reflects the
        full sweep total. Pulls from self._last_results since by this
        point the streaming counters in _render's closure are out of
        scope."""
        results = self._last_results or []
        total = len(results)
        flagged = sum(1 for r in results if r.get("flagged"))
        date_part = f"{self.run_date}  ·  " if self.run_date else ""
        self.status_label.configure(
            text=f"{date_part}{total} jobs  ·  "
                 f"{flagged} flagged  ·  {total - flagged} OK")

    def audit_single_client(self, name, *, folder_override=None,
                              then_open_sp=False):
        """Public single-client audit hook for cross-tab callers.

        SP Recent's Pin-&-Audit and Import-SP flows use this: the audit
        runs for the named client, and when `then_open_sp=True` the SP
        download dialog auto-opens for the resulting row so the user
        lands directly on the import flow instead of having to click
        the row's `📥 SP` pill themselves.

        Same flow as `_audit_one_job` but skipping the typed-name
        prompt — the caller already knows the name."""
        if not name or not name.strip():
            return
        name = name.strip()
        if folder_override:
            try:
                persistence.set_folder_path(name, folder_override)
            except Exception:
                pass
        # Mark single-job mode so the "↺ Run Audit" rerun button + the
        # force-sync / Find Folder per-card refresh path re-run THIS
        # single client (not the daily-run sweep). Cleared by
        # `_run_audit` when the user explicitly chooses daily again.
        self._set_last_audit_kind("single", name)
        # Bump the epoch so any pending enqueues from the previous
        # (full / single) audit don't leak orphan cards into this view.
        self._audit_run_epoch += 1
        self._virt_cards.clear()
        self._card_by_client.clear()
        for w in self._inner.winfo_children():
            w.destroy()
        self.update_idletasks()
        try:
            self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        self.status_label.configure(text=f"Auditing '{name}'…")
        self.show_loading(f"Auditing {name}…")
        self.update()
        run_date = self.run_date or datetime.today().strftime("%m-%d-%Y")
        # Stash the resolved run_date on self so downstream callers
        # like `_refresh_single_card` (used by force-sync, find-folder,
        # change-folder) re-audit against the same date the user was
        # working with. Without this, force-sync after a single-job
        # audit ran with `run_date=None` and produced a result that
        # didn't match the canonicalized client key — triggering the
        # "card refresh hiccup → full audit" fallback and blowing
        # away the single-job view.
        self.run_date = run_date
        from audit_logic import make_folder_lookup
        _lookup = make_folder_lookup(folder_override, name)

        def _thread():
            try:
                results, err = audit_jobs(
                    [{"client": name, "raw": ""}], run_date=run_date,
                    folder_path_lookup=_lookup)
            except Exception as ex:
                results, err = None, str(ex)
            if results:
                for r in results:
                    try:
                        enrich_with_sharepoint(r, run_date)
                    except Exception:
                        pass
            def _done():
                self.hide_loading()
                # Render only when the Daily Run body itself is
                # currently mapped — `self` is the audit ToolPanel
                # which stays mapped even when the user has switched
                # to a sibling tab (Initial Upload / Backlog / SP
                # Recent). Without checking the body, _render() ran
                # against a hidden frame and produced no visible
                # output even though the audit had completed.
                if not self._run_body.winfo_ismapped():
                    self._pending_render = (results, err)
                else:
                    self._render(results, err)
                # Chain into the SP download dialog when the caller
                # asked for it. Open it regardless of whether
                # `sharepoint_matches` is populated — the dialog itself
                # surfaces a "📎 Pin folder…" button so the user can
                # attach an SP folder manually when the auto-matcher
                # found nothing. Schedule via after() so the render
                # completes first — opening a Toplevel mid-render
                # fights the layout pass.
                if then_open_sp and results:
                    first = results[0] if results else None
                    if first:
                        self.after(50,
                            lambda r=first: self._open_sharepoint_download_dialog(r))
            self.after(0, _done)
        threading.Thread(target=_thread, daemon=True).start()

    def _try_trello_folder_resolve(self, client):
        """Auto-resolve a missing job folder by looking up the pinned
        Trello card's desc and trying its CUSTOMER NAME / ADDRESS / etc.
        as alternate folder-name search terms.

        Returns `(absolute_path, folder_basename, year, hit_term)` on a
        unique match, or None when there's no pinned card, no card desc,
        or no unique folder hit. Network call to Trello is on the UI
        thread but bounded — one card fetch + one local directory scan.
        Acceptable cost for the rare "click Find Folder" path."""
        if not client:
            return None
        try:
            import trello_client as _tc
            import audit_logic as _al
        except Exception:
            return None
        try:
            pinned_ids = persistence.get_trello_card_ids(client) or []
        except Exception:
            pinned_ids = []
        if not pinned_ids:
            return None
        for cid in pinned_ids:
            try:
                card = _tc.get_card(cid, actions_limit=0)
            except Exception:
                card = None
            if not card:
                continue
            try:
                terms = _tc.card_folder_search_terms(card)
            except Exception:
                terms = []
            if not terms:
                continue
            try:
                hit = _al.try_resolve_folder_by_terms(AUDIT_BASE, terms)
            except Exception:
                hit = (None, None, None)
            full_path, name, year = hit
            if not full_path:
                continue
            # Identify WHICH term triggered the match so the confirm
            # dialog can show the user the resolver's reasoning.
            hit_term = terms[0]
            for t in terms:
                try:
                    single = _al.try_resolve_folder_by_terms(
                        AUDIT_BASE, [t])
                except Exception:
                    single = (None, None, None)
                if single[0] == full_path:
                    hit_term = t
                    break
            return (full_path, name, year, hit_term)
        return None

    def _post_audit_comment_to_trello(self, client, issue_text,
                                       issue_key, card_ids):
        """Open a small composer dialog with the templated text, let the
        user edit, post to every pinned card on confirm. Marks the
        client+issue as recently-commented so the per-row button greys
        out on subsequent re-renders within the guard window.

        Posting fans out to every pinned card (commercial jobs often
        have 2-3 cards for the same client — initial + monitor +
        recon). Failures are surfaced individually so the user knows
        if one card couldn't be reached."""
        if not client or not card_ids:
            return
        try:
            import trello_client as _tc
        except Exception:
            messagebox.showerror(
                "Trello unavailable",
                "Could not load trello_client.", parent=self)
            return
        default_text = _tc.audit_finding_comment_template(issue_text)

        dlg = tk.Toplevel(self)
        dlg.title("Post comment to Trello")
        dlg.transient(self.winfo_toplevel())
        dlg.resizable(True, True)
        dlg.geometry("520x260")
        frame = tk.Frame(dlg, bg=WHITE, padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(frame,
                 text=f"Comment on {len(card_ids)} pinned card"
                      f"{'s' if len(card_ids) != 1 else ''} "
                      f"for {client}:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w"
                 ).pack(fill="x")
        tk.Label(frame,
                 text=f"Finding: {issue_text}",
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=WHITE, fg=TEXT_GRAY, anchor="w"
                 ).pack(fill="x", pady=(0, 8))
        txt = tk.Text(frame, wrap="word", font=("Segoe UI Variable", 10),
                       height=6,
                       bg=WHITE, relief="solid", bd=1)
        txt.insert("1.0", default_text)
        txt.pack(fill="both", expand=True)
        btn_row = tk.Frame(frame, bg=WHITE)
        btn_row.pack(fill="x", pady=(10, 0))

        result_holder = {"posted": False}

        def _do_post():
            text = txt.get("1.0", "end").strip()
            if not text:
                return
            ok_count = 0
            err = None
            for cid in card_ids:
                try:
                    if _tc.post_comment(cid, text):
                        ok_count += 1
                except Exception as ex:
                    err = str(ex)
            if ok_count:
                try:
                    persistence.mark_audit_comment_posted(
                        client, issue_key, run_date=self.run_date)
                except Exception:
                    pass
                result_holder["posted"] = True
                try:
                    show_toast(
                        self,
                        f"Posted to {ok_count}/{len(card_ids)} card"
                        f"{'s' if len(card_ids) != 1 else ''}",
                        kind="info")
                except Exception:
                    pass
                dlg.destroy()
                # Re-render this card so the button greys out.
                try:
                    self._refresh_single_card(client)
                except Exception:
                    pass
            else:
                messagebox.showerror(
                    "Post failed",
                    err or "Trello rejected the post — check your token.",
                    parent=dlg)

        tk.Button(btn_row, text="Cancel", font=("Segoe UI Variable", 9),
                   bg=WHITE, fg=TEXT_DARK, activebackground=NEUTRAL_HOVER,
                   relief="solid", bd=1, padx=12, pady=3, cursor="hand2",
                   command=dlg.destroy
                   ).pack(side="right")
        tk.Button(btn_row, text="Post to Trello",
                   font=("Segoe UI Variable", 9, "bold"),
                   bg=INFO_BG, fg=INFO_FG, activebackground=INFO_HOVER,
                   relief="flat", padx=12, pady=3, cursor="hand2",
                   command=_do_post
                   ).pack(side="right", padx=(0, 6))

        dlg.update_idletasks()
        try:
            px = (self.winfo_rootx()
                  + max(0, (self.winfo_width() - 520) // 2))
            py = (self.winfo_rooty()
                  + max(0, (self.winfo_height() - 260) // 2))
            dlg.geometry(f"+{px}+{py}")
        except Exception:
            pass
        txt.focus_set()
        dlg.grab_set()

    def _open_unit_picker(self, r, unit_subs):
        """Modal that lets the user pin one OR more unit subfolders to
        this row for today's run. `unit_subs` is the prefetched output
        of `audit_logic.list_unit_subfolders(r["path"])`.

        Multi-select: each unit has a checkbox. The Apply button writes
        every selected path via `persistence.set_run_day_units(...)`.
        When multiple units are selected, the audit replicates the row
        — one card per pinned unit — on the next refresh.

        Clear button drops every day-pin for this row, returning to
        the umbrella folder."""
        client = r.get("client") or ""
        if not client or not unit_subs:
            return
        try:
            current_paths = set(
                persistence.get_run_day_units(self.run_date, client))
        except Exception:
            current_paths = set()

        dlg = tk.Toplevel(self)
        dlg.title(f"Pick units for {client}")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("480x500")
        except tk.TclError:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head, text=f"🏠 Pick units for {client}",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
        tk.Label(head,
                 text=("Check every unit this row covers. Multi-pin "
                       "replicates the audit row — one card per unit. "
                       "Day-only: tomorrow's audit re-derives from "
                       "scratch. Right-click row → Change folder… for "
                       "a permanent pin."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=440, justify="left", anchor="w"
                 ).pack(fill="x", pady=(4, 0))

        body_wrap = tk.Frame(dlg, bg=BG, padx=14)
        body_wrap.pack(fill="both", expand=True)
        scroll = ScrollableFrame(body_wrap, bg=BG, canvas_bg=WHITE)
        scroll.pack(fill="both", expand=True)

        # Per-unit BooleanVar — seeded from the current day-pin set so
        # re-opening the dialog reflects what's already pinned.
        sel_vars: dict[str, tk.BooleanVar] = {}
        for u in unit_subs:
            sel_vars[u["path"]] = tk.BooleanVar(
                value=(u["path"] in current_paths))

        def _apply():
            chosen = [p for p, v in sel_vars.items() if v.get()]
            try:
                persistence.set_run_day_units(self.run_date,
                                                client, chosen)
            except Exception as ex:
                messagebox.showerror("Save failed", str(ex), parent=dlg)
                return
            dlg.destroy()
            if not chosen:
                show_toast(self,
                           f"Cleared day-pins for {client}",
                           kind="info")
            elif len(chosen) == 1:
                show_toast(self,
                           f"Pinned {client} to 1 unit for today",
                           kind="info")
            else:
                show_toast(self,
                           f"Pinned {client} to {len(chosen)} units "
                           "for today — rerunning audit",
                           kind="info")
            # Multi-pin needs a full re-run because the row count
            # changes (replication into N rows). Single or zero pins
            # can refresh just this row.
            try:
                if len(chosen) > 1 or (chosen and not current_paths):
                    # Falling into multi-pin OR adding a fresh pin
                    # that may flip rendering — rerun is safer than
                    # patching one card. Dispatcher keeps single-job
                    # context if that's where the user was.
                    self._rerun_current_audit()
                else:
                    self._refresh_single_card(client)
            except Exception:
                try:
                    self._rerun_current_audit()
                except Exception:
                    pass

        def _clear_all():
            for v in sel_vars.values():
                v.set(False)
            _apply()

        for u in unit_subs:
            row_f = tk.Frame(scroll.inner, bg=WHITE,
                              highlightthickness=1,
                              highlightbackground=BORDER)
            row_f.pack(fill="x", padx=2, pady=2)
            inner_f = tk.Frame(row_f, bg=WHITE, padx=10, pady=6)
            inner_f.pack(fill="x")
            cb = tk.Checkbutton(
                inner_f, text=u["name"],
                variable=sel_vars[u["path"]],
                font=("Segoe UI Variable", 10), bg=WHITE, fg=TEXT_DARK,
                activebackground=WHITE,
                anchor="w", padx=4, cursor="hand2")
            cb.pack(side="left", fill="x", expand=True)

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(fill="x", side="bottom")
        tk.Button(bot, text="✓ Apply",
                  font=("Segoe UI Variable", 9, "bold"), bg=INFO_BG, fg=INFO_FG,
                  activebackground=INFO_HOVER,
                  relief="solid", bd=1, padx=14, pady=4, cursor="hand2",
                  command=_apply
                  ).pack(side="right", padx=(8, 0))
        tk.Button(bot, text="Cancel",
                  font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_DARK,
                  activebackground=NEUTRAL_HOVER,
                  relief="solid", bd=1, padx=12, pady=4, cursor="hand2",
                  command=dlg.destroy
                  ).pack(side="right")
        if current_paths:
            tk.Button(bot, text="✕ Clear all",
                      font=("Segoe UI Variable", 9), bg=WHITE, fg=FLAG_RED,
                      activebackground=DANGER_HOVER,
                      relief="solid", bd=1, padx=12, pady=4,
                      cursor="hand2", command=_clear_all
                      ).pack(side="left")

    def _scaffold_ems_for_row(self, client, path):
        """Create the EMS / EMS/DOCS / EMS/PICS subfolders inside
        `path` (the job's OD folder), then re-audit just this row so
        the badge / chip state updates.

        Wired to the 📁+ button surfaced on audit rows whose resolved
        folder is missing any of those three subfolders. Idempotent —
        existing folders are left alone (`exist_ok=True`)."""
        if not path or not client:
            return
        created = []
        errored = []
        for sub in (os.path.join(path, "EMS"),
                    os.path.join(path, "EMS", "DOCS"),
                    os.path.join(path, "EMS", "PICS")):
            if os.path.isdir(sub):
                continue
            try:
                os.makedirs(sub, exist_ok=True)
                created.append(os.path.basename(sub))
            except OSError as ex:
                errored.append(f"{os.path.basename(sub)} ({ex})")
        if errored:
            try:
                show_toast(self,
                           f"Couldn't create: {', '.join(errored)}",
                           kind="error")
            except Exception:
                pass
            return
        if created:
            try:
                show_toast(self,
                           f"Created {', '.join(created)} for {client}",
                           kind="info")
            except Exception:
                pass
        # Re-audit the row so the 📁+ button drops off + any new
        # photo/form scans pick up the fresh structure.
        try:
            self._refresh_single_card(client)
        except Exception:
            pass

    def _pin_folder_and_refresh_row(self, client, path):
        """Common tail used by Find Folder / Trello auto-resolve /
        right-click Change Folder: scaffold EMS layout, pin the override,
        toast, refresh just this row."""
        if not client or not path:
            return
        try:
            for sub in (os.path.join(path, "EMS"),
                        os.path.join(path, "EMS", "DOCS"),
                        os.path.join(path, "EMS", "PICS")):
                if not os.path.isdir(sub):
                    try:
                        os.makedirs(sub, exist_ok=True)
                    except OSError:
                        pass
        except Exception:
            pass
        try:
            persistence.set_folder_path(client, path)
        except Exception:
            pass
        try:
            show_toast(self, f"OD folder pinned for {client}", kind="info")
        except Exception:
            pass
        self._refresh_single_card(client)

    def _check_sync_state(self, r):
        """Compute (and cache on the row dict) the number of OneDrive
        cloud-only placeholders under this audit row's resolved path.

        Cached so a single-card refresh doesn't re-walk the tree. The
        cache lives on `r` itself (`_sync_unsynced` count + `_sync_samples`
        list of basenames for the tooltip).

        Returns the unsynced count (int)."""
        if "_sync_unsynced" in r:
            return r["_sync_unsynced"]
        try:
            import sp_sync_state
            result = sp_sync_state.count_cloud_only(r.get("path") or "")
        except Exception:
            r["_sync_unsynced"] = 0
            r["_sync_samples"] = []
            return 0
        r["_sync_unsynced"] = int(result.get("unsynced") or 0)
        r["_sync_samples"] = list(result.get("samples") or [])
        return r["_sync_unsynced"]

    def _force_sync_row(self, r, btn):
        """Background-pull every cloud-only file under this audit row.

        Disables the button while running, surfaces progress in a toast,
        clears the row's sync cache, and re-renders the single card so
        the ☁ chip drops once OneDrive has pulled everything down.

        Runs off the UI thread because each file is a network
        round-trip — a job with 200 cloud-only photos would freeze the
        panel for tens of seconds otherwise."""
        path = r.get("path") or ""
        client = r.get("client") or ""
        if not path:
            return
        try:
            btn.configure(state="disabled", text="…")
        except Exception:
            pass
        try:
            show_toast(self,
                       f"Force-syncing OneDrive files for {client}…",
                       kind="info")
        except Exception:
            pass

        def _bg():
            try:
                import sp_sync_state
                result = sp_sync_state.force_pull(path)
            except Exception as ex:
                result = {"error": str(ex)}

            def _done():
                # Audit panel may have been navigated away from while
                # the pull was running — winfo_exists guards prevent
                # "bad window path name" when btn/self are gone.
                try:
                    if btn.winfo_exists():
                        btn.configure(state="normal", text="🔄")
                except Exception:
                    pass
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                if "error" in result:
                    try:
                        show_toast(self,
                                   f"Force-sync failed: {result['error']}",
                                   kind="error")
                    except Exception:
                        pass
                    return
                pulled = int(result.get("pulled") or 0)
                failed = int(result.get("failed") or 0)
                elapsed = result.get("elapsed_s") or 0
                msg = (f"Pulled {pulled} file(s) for {client} "
                       f"in {elapsed}s")
                if failed:
                    msg += f" — {failed} failed"
                try:
                    show_toast(self, msg,
                               kind="warn" if failed else "info")
                except Exception:
                    pass
                # Drop the cached sync state so the next render re-walks
                # and the chip updates (or disappears) to match reality.
                r.pop("_sync_unsynced", None)
                r.pop("_sync_samples", None)
                self._refresh_single_card(client)
            try:
                self.after(0, _done)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _refresh_single_card(self, client):
        """Re-audit one client and swap its card in place — no full
        panel re-render. Used by Find Folder / right-click "Change
        folder…" so pinning an OD path for one job doesn't redraw every
        other row on screen.

        Falls back to a full `_run_audit()` when the per-card closure
        isn't available yet (e.g. user clicked before the first audit
        finished) — there's nothing in the card-by-client map to swap.
        """
        client = (client or "").strip()
        if not client:
            return
        if not callable(getattr(self, "_render_one_card_fn", None)):
            # Per-card closure unavailable (panel hasn't rendered yet
            # / closure invalidated). Dispatch through the rerun
            # helper so a single-job view stays single-job instead of
            # being silently replaced by the daily-run sweep.
            self._rerun_current_audit()
            return
        # Re-audit JUST this client. audit_jobs honors the pinned folder
        # we just set via persistence.set_folder_path, so the fresh r
        # picks up the new path + recomputes flags/photos/forms.
        try:
            # year=None lets audit_logic resolve from the pinned folder.
            # use_cache=False because the pin just changed — a cached
            # result against the OLD folder would skip the re-audit.
            new_rs = audit_jobs([client],
                                  year=None,
                                  run_date=self.run_date,
                                  use_cache=False)
        except Exception as ex:
            show_toast(self, f"Re-audit failed: {ex}", kind="error")
            return
        if not new_rs:
            return
        new_r = new_rs[0]
        # Pull SharePoint matches the same way the full _run_audit does,
        # otherwise the 📥 SP pill renders empty after the refresh.
        try:
            enrich_with_sharepoint(new_r, self.run_date)
        except Exception:
            pass

        # Find the old card + the widget that sits immediately below it
        # so we can repack the fresh card at the same vertical slot.
        old_card = self._card_by_client.get(client)
        before_sibling = None
        if old_card is not None:
            try:
                siblings = self._inner.winfo_children()
                idx = siblings.index(old_card)
                if idx + 1 < len(siblings):
                    before_sibling = siblings[idx + 1]
            except (ValueError, tk.TclError):
                before_sibling = None
            try:
                old_card.destroy()
            except tk.TclError:
                pass
            self._card_by_client.pop(client, None)

        # Update self._last_results so downstream calls (snapshot push,
        # export, etc.) see the fresh row instead of the stale one.
        if isinstance(self._last_results, list):
            for i, r in enumerate(self._last_results):
                if (r.get("client") or "").strip() == client:
                    self._last_results[i] = new_r
                    break
            else:
                self._last_results.append(new_r)

        render_ex = None
        try:
            self._render_one_card_fn(new_r, before=before_sibling)
        except Exception as ex:
            render_ex = ex
        # Verify the row actually landed in the panel. The single-card
        # render path packs into self._inner using `before=`; if the
        # before-sibling is stale or the render closure threw, the new
        # card never lands and the user sees the row vanish — which
        # was the "row disappears after picking a unit" bug. Fall back
        # to a full audit so the user gets every row back instead.
        #
        # Look up by BOTH the input `client` and the new result's own
        # client field — when audit_logic canonicalizes a name
        # ("santiago, ernie" → "Santiago, Ernie") the map gets keyed
        # by the canonical form, so the original lookup misses.
        # Without this, force-sync after a single-job audit blew away
        # the single-job view by falling through to _run_audit().
        new_card = None
        if not render_ex:
            new_card = self._card_by_client.get(client)
            if new_card is None:
                alt = (new_r.get("client") or "").strip()
                if alt and alt != client:
                    new_card = self._card_by_client.get(alt)
        if render_ex or new_card is None:
            try:
                import traceback as _tb
                print(f"[_refresh_single_card] render failed for "
                      f"{client!r}: {render_ex!r}", flush=True)
                if render_ex:
                    _tb.print_exception(
                        type(render_ex), render_ex,
                        render_ex.__traceback__)
            except Exception:
                pass
            # Re-run via the current-audit dispatcher so a single-job
            # view doesn't get silently swapped for the daily run when
            # the per-card swap fails. The toast text adapts so the
            # user knows which kind of audit is about to re-run.
            _kind, _target = self._last_audit_kind
            if _kind == "single" and _target:
                _toast = (f"Card refresh hiccup — re-running audit "
                           f"for {_target}")
            else:
                _toast = "Card refresh hiccup — re-running full audit"
            show_toast(self, _toast, kind="info")
            try:
                self._rerun_current_audit()
            except Exception:
                pass
            return
        # Re-attach default tooltips to any inline widgets the fresh
        # render spawned (covers the FLAG/OK badge, time-slot pill,
        # icon cluster, etc).
        try:
            self.after_idle(self.sweep_tooltips)
        except Exception:
            pass

    def _audit_one_job(self):
        """Audit a single insured by typed name, no run doc required.
        Optionally accepts an explicit folder override so the user can
        point the audit at the exact job folder when the matcher's
        year-folder search would otherwise pick the wrong one (e.g.,
        repeat insureds across years, ambiguous unit jobs)."""
        result = self._prompt_audit_one_job()
        if not result:
            return
        name, folder_override = result
        # Persist the picked folder so the next audit of this insured
        # (in Run Audit OR Snapshot) auto-resolves to the same path
        # without having to re-pick. Mirrors the Find-Folder memory in
        # the per-row override flow.
        if folder_override:
            try:
                persistence.set_folder_path(name, folder_override)
            except Exception:
                pass
        # Mark single-job mode so the "↺ Run Audit" rerun + per-card
        # refresh fallbacks re-run THIS job, not the daily sweep.
        self._set_last_audit_kind("single", name)

        # Bump the audit-run epoch BEFORE clearing _inner — any
        # in-flight cards from a prior streaming audit (e.g., the
        # daily-run audit's worker thread is still draining results)
        # see a stale epoch and skip painting. Without this, those
        # leftover cards continued to land in _inner AFTER we cleared
        # it for the single-job audit, which is what the user saw as
        # "it constantly loads more than my one job from the daily
        # run." Mirrors `audit_single_client` (line 2310) which
        # already had the epoch bump for the same reason.
        self._audit_run_epoch += 1
        my_epoch = self._audit_run_epoch
        self._virt_cards.clear()
        self._card_by_client.clear()
        for w in self._inner.winfo_children():
            w.destroy()
        self.update_idletasks()
        try:
            self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        # Drop any pending render queued from a prior audit (full or
        # streaming) so it can't fire after this single-job clear.
        self._pending_render = None
        self._streaming_buffer = []
        self._streaming_drain_pending = False
        self.status_label.configure(text=f"Auditing '{name}'…")
        self.show_loading(f"Auditing {name}…")
        self.update()

        run_date = self.run_date or datetime.today().strftime("%m-%d-%Y")

        # Build the override-aware lookup via the shared helper so the
        # behavior is identical to Snapshot's Audit Only path.
        from audit_logic import make_folder_lookup
        _lookup = make_folder_lookup(folder_override, name)

        def _thread():
            try:
                results, err = audit_jobs(
                    [{"client": name, "raw": ""}], run_date=run_date,
                    folder_path_lookup=_lookup)
            except Exception as ex:
                results, err = None, str(ex)
            if results:
                for r in results:
                    try:
                        enrich_with_sharepoint(r, run_date)
                    except Exception:
                        pass
            def _done():
                # If the user kicked off another audit while this one
                # was running, abandon — stops this thread from painting
                # into a freshly-cleared _inner.
                if self._audit_run_epoch != my_epoch:
                    return
                self.hide_loading()
                # Render only when the Daily Run body itself is
                # currently mapped — `self` is the audit ToolPanel
                # which stays mapped even when the user has switched
                # to a sibling tab (Initial Upload / Backlog / SP
                # Recent). Without checking the body, _render() ran
                # against a hidden frame and produced no visible
                # output even though the audit had completed.
                if not self._run_body.winfo_ismapped():
                    self._pending_render = (results, err)
                else:
                    self._render(results, err)
            self.after(0, _done)

        threading.Thread(target=_thread, daemon=True).start()

    def _prompt_audit_one_job(self):
        """Thin shim around the shared dialog so existing callers don't
        have to learn the kwarg form."""
        from job_widgets import prompt_audit_folder_override
        return prompt_audit_folder_override(
            self, prompt_for_name=True,
            initial_dir=AUDIT_BASE, title="Audit One Job")

    def _audit_named_jobs(self, names, source_label="selection"):
        """Run the main audit pipeline against an explicit list of insured
        names. Same code path as a full sweep — folder lookup, photo
        cross-check, SP enrichment — minus the run-doc parsing step.
        Used by the stale-backlog dialog so the user can re-audit jobs
        that fell off the daily run-doc."""
        if not names:
            return
        self._virt_cards.clear()
        for w in self._inner.winfo_children():
            w.destroy()
        self.update_idletasks()
        try:
            self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        self.status_label.configure(
            text=f"Auditing {len(names)} {source_label} job"
                 f"{'s' if len(names) != 1 else ''}…")
        self.show_loading(f"Auditing {len(names)} jobs…")
        self.update()

        run_date = self.run_date or datetime.today().strftime("%m-%d-%Y")
        job_dicts = [{"client": n, "raw": ""} for n in names]

        def _thread():
            try:
                results, err = audit_jobs(job_dicts, run_date=run_date)
            except Exception as ex:
                results, err = None, str(ex)
            if results:
                # Reuse the multi-client SP index pre-walk so the stale
                # batch doesn't pay a per-client folder-tree scan.
                try:
                    from sharepoint import build_sharepoint_folder_index
                    folder_index = build_sharepoint_folder_index()
                except Exception:
                    folder_index = None
                match_cache = {}
                for r in results:
                    try:
                        enrich_with_sharepoint(
                            r, run_date,
                            folder_index=folder_index,
                            match_cache=match_cache)
                    except Exception:
                        pass
            def _done():
                self.hide_loading()
                # Render only when the Daily Run body itself is
                # currently mapped — `self` is the audit ToolPanel
                # which stays mapped even when the user has switched
                # to a sibling tab (Initial Upload / Backlog / SP
                # Recent). Without checking the body, _render() ran
                # against a hidden frame and produced no visible
                # output even though the audit had completed.
                if not self._run_body.winfo_ismapped():
                    self._pending_render = (results, err)
                else:
                    self._render(results, err)
            self.after(0, _done)

        threading.Thread(target=_thread, daemon=True).start()

    def _show_match_diagnostic(self, r, m):
        """Pop up a diagnostic for one SP match: why the matcher picked
        this folder, what search terms it used, and where to look in
        state.json if the user wants to clear an override.

        Triggered by the per-row "🔍 Why?" button in the SharePoint
        download dialog. Read-only — informational only."""
        from sharepoint import _name_search_terms
        client = r.get("client") or ""
        full, last, _first = _name_search_terms(client)
        unit   = r.get("unit") or ""
        tenant = r.get("tenant") or ""
        if tenant:
            tenant_full, tenant_last, _tenant_first = _name_search_terms(tenant)
        else:
            tenant_full, tenant_last = "", ""
        try:
            overrides = persistence.get_sp_match_overrides(client)
        except Exception:
            overrides = []
        try:
            rejects = persistence.get_sp_match_rejects(client)
        except Exception:
            rejects = set()
        is_override = m.get("override") or m.get("path") in overrides
        path = m.get("path") or ""
        folder = m.get("name") or ""
        nl = folder.lower()
        reason = m.get("match_reason") or "(unknown — pre-upgrade match)"

        lines = [
            f"Folder: {folder}",
            f"Path:   {path}",
            f"Files:  {m.get('count', 0)}",
            "",
            f"Match reason: {reason}",
            "",
            "Search terms used:",
            f"  • client full:    {full!r}",
            f"  • client last:    {last!r}  (used when ≥3 chars)",
        ]
        if unit:
            lines.append(f"  • unit:           {unit!r}  (word-boundary match)")
        if tenant:
            lines.append(f"  • tenant full:    {tenant_full!r}")
            lines.append(f"  • tenant last:    {tenant_last!r}  (used when ≥3 chars)")
        lines.append("")
        lines.append(f"Folder lowercased: {nl!r}")
        lines.append("")
        if is_override:
            lines.append(
                "STATUS: User-pinned override — this folder is included "
                "regardless of name match. Hit '× Unpin' on the row to remove.")
        elif m.get("path") in rejects:
            lines.append(
                "STATUS: Previously rejected — should NOT appear here. "
                "If you see this message, please report it.")
        else:
            lines.append(
                "STATUS: Auto-match — passed substring check above. "
                "Hit '✗ Wrong job' on the row to suppress future matches.")

        # Use a small Toplevel rather than messagebox so the path stays
        # selectable + copy-able.
        win = tk.Toplevel(self)
        win.title(f"Why matched? — {folder[:40]}")
        win.transient(self.winfo_toplevel())
        win.resizable(True, False)
        try:
            win.grab_set()
        except tk.TclError:
            pass
        frm = tk.Frame(win, bg=BG, padx=14, pady=12)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, font=("Consolas", 9), wrap="word",
                      height=min(20, len(lines) + 2), width=80,
                      bg=WHITE, fg=TEXT_DARK, relief="flat",
                      borderwidth=1, highlightthickness=1,
                      highlightbackground=BORDER)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")
        bot = tk.Frame(frm, bg=BG)
        bot.pack(fill="x", pady=(10, 0))
        tk.Button(bot, text="Close", font=("Segoe UI Variable", 9, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=14, pady=4, cursor="hand2",
                  command=win.destroy).pack(side="right")

    def _rescan_sharepoint_for_result(self, r, run_date):
        """Re-walk OD and SharePoint for one audit row and refresh the
        diff stats on `r` in place. Thin wrapper around the shared
        `enrich_with_sharepoint` helper — kept as a method so the dialog
        callsites don't have to know whether to import the module-level
        function or the method."""
        # Bulk scan only assigns sharepoint_matches when matches exist.
        # The rescan path needs to also CLEAR them when matches drop to
        # zero (e.g. user rejected the last remaining wrong-job folder),
        # so explicitly reset before enriching.
        r["sharepoint_matches"] = []
        r["sharepoint_new"]     = 0
        enrich_with_sharepoint(r, run_date)

    def _open_sharepoint_download_dialog(self, r, on_close_changed=None):
        """Direct-copy SharePoint photos into the job's OneDrive PICS tree.

        PHOTOS_ROOT is a mounted share, so we have file-level access. Lists
        each tech-folder match for this client with a per-row "📥 Copy +N
        new" button that copies just the diff files (not already under
        OD/PICS) into ``<PICS>/From SharePoint - <tech>/<folder name>/`` in
        a background thread with a live progress label. The user can also
        "📁 Open" any folder to browse before copying.

        ``on_close_changed`` — optional callback fired exactly once when
        the dialog is closed AFTER any modifying action has run (copy,
        mark-in-OD, reject). Lets the parent audit row update its
        right-side pills (📷 N count, 📥 SP +N new) in place instead of
        forcing a full re-audit.
        """
        # Tracks whether the user did anything that should trigger a
        # parent-row refresh on close. Flipped by _bulk_copy /
        # _bulk_mark_in_od / _bulk_reject and the per-row equivalents.
        # A list cell so nested closures can mutate it.
        _did_modify = [False]
        matches = r.get("sharepoint_matches") or []
        if not matches:
            # Unit-strict search returned nothing. For multi-unit jobs
            # this is most often because the tech filed the SP folder
            # without the unit number AND without the tenant name —
            # both are required signals in unit mode (property-name
            # alone is too broad). Re-run as a soft fallback WITHOUT
            # the unit constraint and surface those property-name hits
            # as ambiguous candidates: the user can pick one if it's
            # clearly the right job, or fall back to manual pinning.
            unit_str = (r.get("unit") or "").strip()
            tenant = (r.get("tenant") or "").strip()
            soft_hits = []
            if unit_str:
                try:
                    from sharepoint import find_sharepoint_folders_for_client
                    extra = []
                    if tenant:
                        extra.append(tenant)
                    try:
                        extra.extend(persistence.get_search_aliases(r["client"]))
                    except Exception:
                        pass
                    soft_hits = find_sharepoint_folders_for_client(
                        r["client"], run_date,
                        extra_names=extra,
                        unit=None,  # property-name fallback
                        folder_index=getattr(self, "_sp_folder_index", None),
                        match_cache=None,
                    ) or []
                except Exception:
                    soft_hits = []

            ctx_bits = [f"Client: {r['client']!r}"]
            if tenant:
                ctx_bits.append(f"Tenant: {tenant!r}")
            if unit_str:
                ctx_bits.append(f"Unit: {unit_str!r}")
            ctx_line = "  •  ".join(ctx_bits)

            if soft_hits:
                names = "\n".join(
                    f"  • {m.get('name') or os.path.basename(m.get('path') or '')}"
                    for m in soft_hits[:8])
                more = (f"\n  …and {len(soft_hits) - 8} more"
                        if len(soft_hits) > 8 else "")
                ans = messagebox.askyesno(
                    "No unit-strict matches",
                    f"No SharePoint folders match the unit/tenant filter.\n\n"
                    f"Searched: {ctx_line}\n\n"
                    f"Found {len(soft_hits)} property-name match"
                    f"{'es' if len(soft_hits) != 1 else ''} "
                    f"WITHOUT the unit filter (likely include other units "
                    f"of the same property):\n{names}{more}\n\n"
                    f"Open the SP dialog with these property-name candidates? "
                    f"Verify each is for Unit {unit_str} before importing.",
                    parent=self)
                if not ans:
                    return
                r["sharepoint_matches"] = soft_hits
                matches = soft_hits
            # else: no auto-matches AND no soft hits. Previous behavior
            # was to bail with an info popup, but the user needs the
            # dialog to STILL open so they can use the "📎 Pin folder…"
            # affordance to attach one manually. Fall through with an
            # empty matches list — the dialog renders a hint + the
            # Pin button.
            else:
                r["sharepoint_matches"] = []
                matches = []
                # Stash context so the dialog can render a friendly
                # "no matches yet — pin one below" hint instead of
                # looking empty for no reason.
                r["_no_match_context"] = ctx_line

        # Gather every PICS variant present so the user can pick one (some
        # jobs need photos under CONTENTS/PICS, not EMS/PICS — e.g. content
        # losses where there's no EMS side at all).
        pics_options = r.get("pics_options")
        if not pics_options:
            job_root = r.get("path")
            all_pics = _resolve_all_pics_folders(job_root)
            pics_options = [
                {"label": l, "path": p, "count": n,
                 "unit_num":  _unit_num_from_pics_path(job_root, p),
                 "unit_name": _unit_segment_from_pics_path(job_root, p)}
                for (l, p, n) in all_pics]
        if not pics_options:
            # No PICS folder anywhere under the job — create EMS/PICS so
            # the SP import has somewhere to land. Most jobs file photos
            # under EMS, so that's the safe default. The user can still
            # change folder via the right-click menu if their photos live
            # under CONTENTS instead.
            job = r.get("path") or ""
            if not job or not os.path.isdir(job):
                messagebox.showerror("No PICS folder",
                    f"Couldn't find the job folder:\n{job}",
                    parent=self)
                return
            new_pics = os.path.join(job, "EMS", "PICS")
            try:
                os.makedirs(new_pics, exist_ok=True)
            except OSError as ex:
                messagebox.showerror("Couldn't create PICS folder",
                    f"Failed to create:\n{new_pics}\n\n{ex}",
                    parent=self)
                return
            show_toast(self,
                       f"Created EMS/PICS for {r['client']}",
                       kind="info")
            pics_options = [{"label": "EMS / PICS",
                              "path":  new_pics,
                              "count": 0}]
            r["pics_options"] = pics_options

        dlg = tk.Toplevel(self)
        dlg.title(f"SharePoint photos — {r['client']}")
        # Resizable now — capped at ~85% of screen height so a huge
        # SharePoint match list (John Camp + similar multi-tech jobs)
        # can't push the dialog past the screen. The match list inside
        # is wrapped in a ScrollableFrame so wheel-scroll works once
        # rows exceed the visible area.
        dlg.resizable(True, True)
        try:
            scr_h = dlg.winfo_screenheight()
            scr_w = dlg.winfo_screenwidth()
            target_h = min(int(scr_h * 0.85), 900)
            target_w = min(int(scr_w * 0.55), 760)
            dlg.geometry(f"{target_w}x{target_h}")
            # Hard cap below the screen edge so the user can always
            # reach the bottom bar buttons even if they manually drag
            # to enlarge.
            dlg.maxsize(scr_w - 40, scr_h - 80)
            dlg.minsize(560, 400)
        except tk.TclError:
            pass
        dlg.grab_set()
        wf = tk.Frame(dlg, bg=BG, padx=20, pady=14)
        wf.pack(fill="both", expand=True)

        # Fire on_close_changed exactly once when the dialog is torn
        # down AFTER the user did anything (copy / mark-in-OD / reject).
        # `<Destroy>` covers both the X-button path and programmatic
        # dlg.destroy() calls; the `e.widget is dlg` filter avoids
        # firing for child-widget destroys that bubble up.
        # We dispatch the callback via `after(0, ...)` so the dialog's
        # destroy finishes BEFORE the refresh runs — otherwise the
        # close visibly stalls while the refresh walks the OneDrive-
        # synced PICS tree to recount photos.
        _close_fired = [False]
        def _fire_close_callback(_e=None):
            if _close_fired[0]:
                return
            _close_fired[0] = True
            if _did_modify[0] and on_close_changed is not None:
                cb = on_close_changed
                def _safe():
                    try:
                        cb()
                    except Exception:
                        pass
                try:
                    self.after(0, _safe)
                except tk.TclError:
                    pass
        dlg.bind("<Destroy>",
                 lambda e: (_fire_close_callback()
                            if e.widget is dlg else None))

        # Summary text — special-case the empty-matches path so the
        # user sees "Pin a folder below" guidance instead of
        # "Found 0 SharePoint folder(s)" which reads broken.
        if matches:
            summary_text = (f"Found {len(matches)} SharePoint folder(s) "
                            f"matching \"{r['client']}\":")
        else:
            summary_text = (
                f"No SharePoint folders auto-matched \"{r['client']}\". "
                f"Use 📎 Pin folder… below to attach one manually.")
        summary_var = tk.StringVar(value=summary_text)
        tk.Label(wf, textvariable=summary_var,
                 font=("Segoe UI Variable", 10, "bold"), bg=BG, fg=TEXT_DARK,
                 anchor="w", justify="left", wraplength=560
                 ).pack(anchor="w")

        # Diagnostic line — shows how many photos we found in OD's job
        # folder. If this is 0 (or wildly low), the walk didn't reach
        # them and nothing will match. Useful for debugging cases like
        # Everhome where photos exist but the diff says they're new.
        diag_var = tk.StringVar()
        diag_lbl = tk.Label(wf, textvariable=diag_var,
                            font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                            anchor="w", justify="left", wraplength=600)
        diag_lbl.pack(anchor="w", pady=(4, 0))

        def _refresh_diagnostic():
            stats = r.get("od_diff_stats") or {}
            scan_path = stats.get("path") or "(no path)"
            diag_var.set(
                f"OD scan: {stats.get('names', 0)} basenames, "
                f"{stats.get('fps', 0)} fingerprints, "
                f"{stats.get('sizes', 0)} sizes\n"
                f"  under: {scan_path}")
            diag_lbl.config(
                fg=("#A04025" if not stats.get('names') else TEXT_GRAY))
        _refresh_diagnostic()

        # Destination row — combobox of every PICS folder under the job.
        # Selection drives where _copy_match writes to. Default = first
        # (which is EMS/PICS when present).
        dest_row = tk.Frame(wf, bg=BG)
        dest_row.pack(fill="x", pady=(6, 4))
        tk.Label(dest_row, text="Copy into:",
                 font=("Segoe UI Variable", 9, "bold"), bg=BG, fg=TEXT_DARK
                 ).pack(side="left")
        dest_label_to_path = {
            f"{o['label']}  ({o['count']} files)": o["path"]
            for o in pics_options
        }
        # Default to the most-active variant — for jobs like Bridgette
        # Miles where the existing photos live under CONTENTS/PICS, that
        # option pre-selects so the user doesn't have to override.
        default_path = _pick_default_pics_path(pics_options)
        default_label = next(
            (k for k, v in dest_label_to_path.items() if v == default_path),
            list(dest_label_to_path.keys())[0])
        dest_var = tk.StringVar(value=default_label)
        dest_cb = ttk.Combobox(dest_row, textvariable=dest_var,
                                state="readonly", width=44,
                                values=list(dest_label_to_path.keys()))
        dest_cb.pack(side="left", padx=(6, 0))
        dest_path_lbl = tk.Label(wf,
                                  text=f"→  {dest_label_to_path[dest_var.get()]}",
                                  font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                                  anchor="w", justify="left", wraplength=560)
        dest_path_lbl.pack(anchor="w", pady=(0, 8))

        def _on_dest_change(_e=None):
            try:
                dest_path_lbl.config(
                    text=f"→  {dest_label_to_path[dest_var.get()]}")
            except (tk.TclError, KeyError):
                pass
        dest_cb.bind("<<ComboboxSelected>>", _on_dest_change)

        def _current_dest():
            return dest_label_to_path.get(dest_var.get())

        # Status line for the active copy operation.
        status_var = tk.StringVar(value="")
        status_lbl = tk.Label(wf, textvariable=status_var,
                              font=("Segoe UI Variable", 9, "italic"),
                              bg=BG, fg=GREEN_DARK,
                              anchor="w", justify="left", wraplength=560)
        status_lbl.pack(anchor="w", pady=(0, 6))

        # Bulk action toolbar — sits above the match list. Each bulk
        # button operates on every row whose select checkbox is ticked.
        # Per-row buttons would otherwise be a click-fest when copying
        # 5+ folders (one for every tech that snapped photos for the
        # job); the toolbar collapses that into one click after a
        # multi-select. Buttons grey out when the selection is empty
        # so the user can't fire a no-op.
        bulk_bar = tk.Frame(wf, bg=BG)
        bulk_bar.pack(fill="x", pady=(0, 4))

        # Track selection state and the bulk-button list so they can
        # update together (selection changes ↔ button enable/disable).
        match_select_vars = {}   # path → BooleanVar
        bulk_buttons      = []
        copy_buttons      = []   # legacy — disabled during copy ops

        select_all_var = tk.BooleanVar(value=False)
        def _refresh_bulk_state(*_):
            n = sum(1 for v in match_select_vars.values() if v.get())
            for btn, label_fmt in bulk_buttons:
                try:
                    btn.config(text=label_fmt.format(n=n),
                               state=("normal" if n else "disabled"))
                except tk.TclError:
                    pass
            sel_btn_text = "☐ Select all" if not match_select_vars or any(
                not v.get() for v in match_select_vars.values()
            ) else "☑ Select none"
            try:
                select_all_btn.config(text=sel_btn_text)
            except tk.TclError:
                pass

        def _toggle_select_all():
            target = any(not v.get() for v in match_select_vars.values())
            for v in match_select_vars.values():
                v.set(target)
            _refresh_bulk_state()

        select_all_btn = tk.Button(
            bulk_bar, text="☐ Select all",
            font=("Segoe UI Variable", 8, "bold"), bg=LINK_BG,
            fg=LINK_FG, activebackground=LINK_HOVER,
            relief="flat", padx=8, pady=3, cursor="hand2",
            command=_toggle_select_all)
        select_all_btn.pack(side="left", padx=(0, 8))

        # Bulk action buttons. Each is greyed out until 1+ rows are
        # selected, and the label shows the selection count so the user
        # can sanity-check before clicking.
        def _add_bulk_btn(text_fmt, cmd, fg, bg, active_bg):
            btn = tk.Button(
                bulk_bar, text=text_fmt.format(n=0),
                font=("Segoe UI Variable", 8, "bold"), bg=bg, fg=fg,
                activebackground=active_bg, relief="flat",
                padx=8, pady=3, cursor="hand2",
                state="disabled", command=cmd)
            btn.pack(side="left", padx=(0, 4))
            bulk_buttons.append((btn, text_fmt))
            return btn

        # Late-bound lambdas — the _bulk_* handlers are defined further
        # down in this same function (after _build_one_match_row). At
        # button-creation time they don't exist yet; resolving by name
        # only when the user clicks lets the closure pick them up.
        _add_bulk_btn("📥 Copy ({n})", lambda: _bulk_copy(),
                      WHITE, GREEN, GREEN_DARK)
        _add_bulk_btn("✓ Mark in OD ({n})", lambda: _bulk_mark_in_od(),
                      GREEN_DARK, "#E8F5EE", "#DAF1E2")
        _add_bulk_btn("✗ Wrong job ({n})", lambda: _bulk_reject(),
                      "#A04025", "#FBEAE5", "#F4D5CD")
        _add_bulk_btn("📁 Open ({n})", lambda: _bulk_open(),
                      TEXT_DARK, "#EEEEEE", "#DDDDDD")
        _add_bulk_btn("📄 Run ({n})", lambda: _bulk_run_doc(),
                      "#2C6FA8", "#EAF3FB", "#D6E7F4")

        def _selected_matches():
            paths = {p for p, v in match_select_vars.items() if v.get()}
            return [m for m in (r.get("sharepoint_matches") or [])
                    if m.get("path") in paths]

        # Match list lives inside a ScrollableFrame so a huge result set
        # doesn't blow the dialog past the screen. ScrollableFrame's
        # mouse-wheel binding is panel-scoped (bindtag) so it doesn't
        # leak to the main audit canvas underneath.
        list_scroll = ScrollableFrame(
            wf, bg=WHITE, canvas_bg=WHITE,
            highlightthickness=1, highlightbackground=BORDER)
        list_scroll.pack(fill="both", expand=True, pady=(0, 10))
        list_card = list_scroll.inner

        def _copy_match(m):
            parent_dest = _current_dest()
            if not parent_dest:
                messagebox.showerror("No destination",
                    "Select a destination folder.", parent=dlg)
                return

            # Multi-unit auto-route: parse the SP folder name for a
            # Unit / Apt / Apartment / #N token and route into that
            # unit's EMS/PICS. When multiple unit folders share the
            # same number (Action Property Management → Villaigo has
            # three "Unit 104" subfolders for different insureds),
            # use insured-name token overlap to disambiguate so
            # "Mendiola unit 104" lands in "Unit 104-97820- Mendiola,
            # Mary" instead of the Straub or Mendoza folder. Falls
            # back to the user's combobox selection when no token
            # parses or no matching unit exists in this job.
            if r.get("is_multi_unit"):
                try:
                    from multi_unit_gui import parse_unit_token
                    sp_name = m.get("name") or ""
                    sp_unit = parse_unit_token(sp_name)
                    if sp_unit is not None:
                        # All unit-scoped options with the matching
                        # unit number. May be multiple if several unit
                        # folders share the same numeric apt #.
                        unit_opts = [o for o in pics_options
                                     if o.get("unit_num") == sp_unit]
                        if unit_opts:
                            sp_tokens = _name_tokens_for_unit_match(sp_name)
                            scored = []
                            for o in unit_opts:
                                opt_tokens = _name_tokens_for_unit_match(
                                    o.get("unit_name") or "")
                                overlap = len(sp_tokens & opt_tokens)
                                # Prefer the PICS leaf over Photos when
                                # tied — historical default.
                                pics_pref = (
                                    1 if (o.get("label") or "")
                                          .rstrip().endswith("PICS")
                                    else 0)
                                scored.append((overlap, pics_pref, o))
                            scored.sort(key=lambda t: (t[0], t[1]),
                                          reverse=True)
                            best_overlap, _, best_opt = scored[0]
                            # Require at least ONE name-token match
                            # when multiple Unit-X options compete —
                            # otherwise we'd be guessing between
                            # equally-eligible folders. Single-option
                            # case keeps the auto-route regardless of
                            # name overlap.
                            if len(unit_opts) == 1 or best_overlap > 0:
                                parent_dest = best_opt["path"]
                except Exception:
                    pass

            # Auto-route into the stage subfolder under the chosen PICS
            # variant when the SP folder name tells us what stage these
            # photos belong to. Created on demand so brand-new stages
            # (e.g. first-ever Mold Prep batch) just work.
            stage_sub = m.get("stage_subfolder") or ""
            if stage_sub:
                dest = os.path.join(parent_dest, stage_sub)
            else:
                dest = parent_dest

            # Re-derive the diff fresh against the WHOLE job folder
            # plus the SP-imported manifest so a previous copy in this
            # same dialog (or a prior audit run) doesn't get re-flagged.
            # Diff is per-file with three keys (basename, (size, mtime)
            # fingerprint, size-only); folder structure is irrelevant.
            try:
                from sharepoint import (
                    list_image_names_in_tree,
                    list_image_fingerprints_in_tree,
                    list_image_size_counts_in_tree,
                )
            except Exception:
                list_image_names_in_tree = None
                list_image_fingerprints_in_tree = None
                list_image_size_counts_in_tree = None
            cur_od_names = set()
            cur_od_fps = set()
            cur_od_size_counts = {}
            # EMS-side only — walk the pics_options roots (see
            # enrich_with_sharepoint for the rationale).
            walk_roots = [opt["path"] for opt in pics_options
                          if os.path.isdir(opt.get("path") or "")]
            for root in walk_roots:
                if list_image_names_in_tree:
                    cur_od_names |= list_image_names_in_tree(root)
                if list_image_fingerprints_in_tree:
                    cur_od_fps |= list_image_fingerprints_in_tree(root)
                if list_image_size_counts_in_tree:
                    for sz, c in list_image_size_counts_in_tree(
                            root).items():
                        cur_od_size_counts[sz] = (
                            cur_od_size_counts.get(sz, 0) + c)
            for opt in pics_options:
                cur_od_names |= _read_sp_manifest_originals(opt["path"])
            # Only safe to size-match against OD sizes that occur
            # exactly once — same reasoning as enrich_with_sharepoint.
            cur_unique_sizes = {sz for sz, c in cur_od_size_counts.items()
                                 if c == 1}
            sp_files = m.get("files") or [
                (n, None) for n in (m.get("filenames") or set())]
            new_set = set()
            for nm, fp in sp_files:
                if nm in cur_od_names:
                    continue
                if fp is not None:
                    if fp in cur_od_fps:
                        continue
                    if fp[0] in cur_unique_sizes:
                        continue
                new_set.add(nm)
            if not new_set:
                messagebox.showinfo("Nothing new",
                    "All files from this folder are already under OD/PICS "
                    "(or have been imported before).",
                    parent=dlg)
                return

            for b in copy_buttons:
                try: b.config(state="disabled")
                except Exception: pass

            # Build the import-folder name once per match. Pattern:
            #   <TECH> <DATE> <CLIENT>[ <TAG>]
            # Files are copied into this folder under their original names
            # so future OD-vs-SP diffs match on basename and the originals
            # remain readable. DATE prefers a date parsed from the SP
            # folder name (techs date their folders), then the SP folder's
            # mtime, then today.
            def _safe(s):
                cleaned = re.sub(r'[\\/:*?"<>|]', "_", str(s or "")).strip()
                return cleaned or "X"
            safe_tech = _safe(m.get("tech"))
            safe_client = _safe(r.get("client"))
            safe_tag = _safe(_sp_folder_tag(m.get("name", ""), r.get("client", "")))
            if safe_tag == "X":
                safe_tag = ""

            folder_date = _extract_date_from_folder_name(m.get("name", ""))
            if folder_date is None:
                try:
                    folder_date = datetime.fromtimestamp(
                        os.path.getmtime(m["path"]))
                except OSError:
                    folder_date = datetime.today()
            # MM-DD-YYYY matches the run-doc date format used everywhere
            # else in the suite (Photo Folders tool, run-doc parsing).
            date_str = folder_date.strftime("%m-%d-%Y")

            folder_parts = [safe_tech, date_str, safe_client]
            if safe_tag:
                folder_parts.append(safe_tag)
            folder_name = " ".join(folder_parts)

            # ── Sticky-home routing ──────────────────────────────────
            # If some files from this SP folder ALREADY live in an OD
            # subfolder, drop the new ones into that same subfolder —
            # keeps related photos together instead of splitting an
            # upload across "Mold Prep/" (where the originals are) and
            # a fresh "<TECH> <DATE> <CLIENT>/" subfolder (where the
            # new ones would otherwise go).
            #
            # Requires ≥1 existing match in the same home folder. The
            # walk is scoped to this job's PICS tree so cross-job false
            # positives aren't a concern — any match here means this
            # batch belongs in that folder.
            home_folder = None
            try:
                from sharepoint import list_image_locations_in_tree
            except Exception:
                list_image_locations_in_tree = None
            if list_image_locations_in_tree:
                # SP-source filenames that already exist somewhere in OD.
                existing_names = [
                    nm for (nm, _fp) in sp_files
                    if nm in cur_od_names and nm not in new_set
                ]
                if existing_names:
                    name_to_folder = {}
                    for root in walk_roots:
                        try:
                            name_to_folder.update(
                                list_image_locations_in_tree(root))
                        except Exception:
                            pass
                    # Tally which OD folder hosts the most matches.
                    from collections import Counter as _Counter
                    folder_counts = _Counter(
                        name_to_folder.get(nm)
                        for nm in existing_names
                        if name_to_folder.get(nm))
                    if folder_counts:
                        best_folder, best_count = (
                            folder_counts.most_common(1)[0])
                        if best_count >= 1 and best_folder:
                            home_folder = best_folder
            if home_folder:
                # Drop straight into the existing home folder — no new
                # "<TECH> <DATE> <CLIENT>" subfolder. The per-file
                # collision-bump (" (N)" suffix) in _thread already
                # handles any filename clashes inside the home folder.
                target_dir = home_folder
                try:
                    os.makedirs(target_dir, exist_ok=True)
                except OSError as ex:
                    messagebox.showerror(
                        "Error",
                        f"Couldn't access existing home folder:\n"
                        f"{target_dir}\n\n{ex}",
                        parent=dlg)
                    return
            else:
                # Reserve the target folder on disk synchronously, BEFORE
                # spawning the copy thread. Bulk-copy fires _copy_match
                # per selected match in a tight loop; when several
                # matches share a folder_name (same tech + same date +
                # same client + same tag — common for back-to-back tech
                # uploads on the same day) the per-thread "exists?"
                # probe used to race, and the losers would either error
                # out or collide. Creating the folder here on the
                # calling thread makes the next match's exists() check
                # see what we just reserved, so subsequent matches
                # deterministically bump to " (2)", " (3)", … and each
                # SP folder lands in its own subfolder.
                target_dir = os.path.join(dest, folder_name)
                n = 2
                while os.path.exists(target_dir):
                    target_dir = os.path.join(
                        dest, f"{folder_name} ({n})")
                    n += 1
                try:
                    os.makedirs(target_dir, exist_ok=False)
                except OSError as ex:
                    messagebox.showerror(
                        "Error",
                        f"Couldn't create:\n{target_dir}\n\n{ex}",
                        parent=dlg)
                    return

            def _thread():
                ok, fail = 0, 0
                imported_originals = []

                # Walk source recursively — copy each image whose basename
                # is in new_set, preserving the source subfolder structure
                # under target_dir. Techs sometimes pre-organize photos
                # into Kitchen/, Bathroom/, Initial/, etc. and want those
                # categories to survive the import. Files at the root of
                # the SP match folder land directly in target_dir.
                try:
                    for root, _dirs, files in os.walk(m["path"]):
                        rel_dir = os.path.relpath(root, m["path"])
                        if rel_dir in (".", ""):
                            sub_target = target_dir
                        else:
                            sub_target = os.path.join(target_dir, rel_dir)
                            try:
                                os.makedirs(sub_target, exist_ok=True)
                            except OSError:
                                pass
                        for f in files:
                            if f.lower() not in new_set:
                                continue
                            src = os.path.join(root, f)
                            stem, ext = os.path.splitext(f)
                            dst = os.path.join(sub_target, f)
                            k = 2
                            while os.path.exists(dst):
                                dst = os.path.join(
                                    sub_target, f"{stem} ({k}){ext}")
                                k += 1
                            try:
                                shutil.copy2(src, dst)
                                ok += 1
                                imported_originals.append(f)
                            except Exception:
                                fail += 1
                            # Throttle UI updates so we don't post 100s
                            # of after() events for a big copy.
                            if (ok + fail) % 5 == 0:
                                self.after(0, lambda d=ok, e=fail:
                                    status_var.set(
                                        f"Copying… {d} done"
                                        + (f", {e} failed" if e else "")))
                except OSError as ex:
                    self.after(0, lambda: messagebox.showerror(
                        "Error", str(ex), parent=dlg))

                # Stamp the new tech folder with the source SP folder's
                # mtime so it sorts and reads as "from that day" in
                # Explorer, not as "created today". shutil.copy2 already
                # preserves each file's mtime — this is just for the
                # parent folder we created via os.makedirs.
                try:
                    src_mtime = os.path.getmtime(m["path"])
                    os.utime(target_dir, (src_mtime, src_mtime))
                except OSError:
                    pass

                # Convert any HEIC files that landed in the target to JPEG.
                try:
                    from wc_zip_import import convert_heic_in_dir
                    convert_heic_in_dir(target_dir)
                except Exception:
                    pass

                # Record the originals so future audits don't re-flag
                # them — the rename means basenames no longer line up
                # with what's on the share. Manifest lives at the PICS
                # *parent*, not the stage subfolder, since the audit
                # walks PICS variants (EMS/PICS, CONTENTS/PICS) when it
                # builds the OD known-set.
                try:
                    _append_sp_manifest_originals(parent_dest, imported_originals)
                except Exception:
                    pass

                # Refresh OD photo count badge on the audit row.
                try:
                    _, n = _resolve_pics_folder(r.get("path"))
                    r["pics_count"] = n
                except Exception:
                    pass

                # Decrement the cached sharepoint_new diff by what we
                # just imported so the on-close refresh has an accurate
                # count to read. Bottom-clamped at 0 — `ok` should never
                # exceed the original diff but Python won't punish us.
                if ok:
                    m["new_count"] = max(0, m.get("new_count", 0) - ok)
                    r["sharepoint_new"] = max(
                        0,
                        sum(mm.get("new_count", 0)
                            for mm in (r.get("sharepoint_matches") or [])))
                    _did_modify[0] = True

                # Auto-tick the matching Trello checklist item — SP
                # photos that landed under PICS/Initial satisfy the
                # "Initial photos" line. We only tick when the target
                # dest resolves to an Initial-side folder; demo/mold-
                # prep imports don't have a mapped checklist item.
                if ok:
                    _dest_lower = (target_dir or "").lower()
                    _is_initial = (
                        os.sep + "initial" in _dest_lower
                        or _dest_lower.endswith("initial"))
                    if _is_initial:
                        try:
                            import persistence as _per
                            _client = (r.get("client") or "").strip()
                            _card_id = (
                                _per.get_trello_card_id(_client) or ""
                                if _client else "")
                            if _card_id:
                                import trello_autotick as _at
                                _at.autotick(
                                    _card_id,
                                    events=("sp_photos_initial",),
                                    client=_client)
                        except Exception:
                            pass

                def _finish():
                    status_var.set(
                        f"Copied {ok} file(s)"
                        + (f"  ·  {fail} failed" if fail else "")
                        + f"  →  {target_dir}")
                    _reenable()
                self.after(0, _finish)

            def _reenable():
                for b in copy_buttons:
                    try: b.config(state="normal")
                    except Exception: pass

            status_var.set(f"Copying {len(new_set)} file(s) from {m['tech']}…")
            threading.Thread(target=_thread, daemon=True).start()

        def _reject_match(m):
            """User says this SP folder is the wrong job (substring search
            pulled e.g. 'Maldanado' for an 'Aldana' query). Persist the
            rejection so it's hidden on every future audit, then rebuild
            the row list and bubble updated counts to the audit row."""
            path = m.get("path")
            if not path:
                return
            # Confirm — accidental clicks here would silently drop a real
            # match and the user might not notice until the audit ships
            # with missing photos. The "↩ Show rejected" button can undo
            # if they really did mean to.
            if not messagebox.askyesno(
                "Mark as wrong job?",
                f"Hide this folder from {r['client']}'s SharePoint matches?\n\n"
                f"   {m.get('tech', '')} / {m.get('name', '')}\n\n"
                "Future audits will skip it. You can undo via "
                "\"↩ Show rejected\" at the bottom of this dialog.",
                parent=dlg):
                return
            persistence.add_sp_match_reject(r["client"], path)
            # _build_match_rows re-applies the reject filter and
            # recomputes sharepoint_new on r. The parent audit row
            # is refreshed once on dialog close via on_close_changed.
            _did_modify[0] = True
            _build_match_rows()
            try:
                show_toast(self,
                    f"Hidden '{m.get('name', '')}' from {r['client']} "
                    "matches — clear from the dialog if undo is needed.",
                    kind="info")
            except Exception:
                pass

        def _unpin_match(m):
            """Remove a user-pinned override. The folder will only return
            to the match list on a future audit if the auto-matcher's
            substring search finds it (i.e., the client's name was added
            to the folder name)."""
            path = m.get("path")
            if not path:
                return
            persistence.remove_sp_match_override(r["client"], path)
            # Drop from the in-memory list and re-render. _build_match_rows
            # re-applies filters and recomputes the row's +N count.
            r["sharepoint_matches"] = [
                mm for mm in (r.get("sharepoint_matches") or [])
                if mm.get("path") != path]
            _build_match_rows()
            try:
                show_toast(self, f"Unpinned '{m.get('name', '')}' from "
                           f"{r['client']} matches.", kind="info")
            except Exception:
                pass

        def _pin_folder():
            """User-driven manual match. Opens a dir picker rooted at
            PHOTOS_ROOT so the user can point at any tech's SP subfolder
            and attach it to this client. Persisted, walked once for the
            file list, then inserted into the dialog as an override row."""
            try:
                from sharepoint import (PHOTOS_ROOT, _build_sp_match,
                                          _date_variants)
            except ImportError as ex:
                messagebox.showerror("SharePoint not available",
                    f"Could not import SP helpers: {ex}", parent=dlg)
                return
            init_dir = PHOTOS_ROOT if os.path.isdir(PHOTOS_ROOT) else None
            picked = filedialog.askdirectory(
                parent=dlg,
                title=f"Pick a SharePoint folder to attach to {r['client']}",
                initialdir=init_dir)
            if not picked:
                return
            # Sanity: folder should sit under PHOTOS_ROOT — otherwise the
            # tech inference is bogus and the audit copy paths break.
            try:
                norm_pick = os.path.normpath(os.path.abspath(picked))
                norm_root = os.path.normpath(os.path.abspath(PHOTOS_ROOT))
                if not norm_pick.startswith(norm_root + os.sep):
                    if not messagebox.askyesno(
                        "Outside SharePoint root?",
                        f"This folder isn't under the configured SharePoint "
                        f"photos root:\n   {PHOTOS_ROOT}\n\nAttach it anyway?",
                        parent=dlg):
                        return
            except Exception:
                pass
            persistence.add_sp_match_override(r["client"], picked)
            dates = _date_variants(self.run_date) if self.run_date else []
            rec = _build_sp_match(picked, dates, override=True)
            if rec is None:
                messagebox.showinfo(
                    "No images",
                    f"That folder has no image files — nothing to attach.\n\n"
                    f"   {picked}",
                    parent=dlg)
                # Roll back the persistence write since the match would
                # never render anyway.
                persistence.remove_sp_match_override(r["client"], picked)
                return
            # Prepend so the new pin sits at the top of the list. The
            # OD-diff (+N new count) only populates after a Refresh —
            # nudge the user to hit it so the Copy button appears.
            existing = r.get("sharepoint_matches") or []
            r["sharepoint_matches"] = [rec] + existing
            _build_match_rows()
            try:
                show_toast(self,
                    f"Pinned '{rec['name']}' — hit 🔄 Refresh to count "
                    "new files vs OD.", kind="success")
            except Exception:
                pass
            # Trigger the existing background refresh so the OD-diff
            # populates without the user having to click.
            try:
                _do_refresh()
            except Exception:
                pass

        def _mark_in_od(m):
            """User says 'these are already in OD, just renamed/recompressed
            so the diff doesn't catch them' — record the SP basenames in
            the manifest at every PICS variant so future audits stop
            flagging them."""
            originals = [n for (n, _fp) in (m.get("files") or [])]
            if not originals:
                originals = sorted(m.get("filenames") or set())
            if not originals:
                messagebox.showinfo("Nothing to mark",
                    "No files in this match.", parent=dlg)
                return
            if not messagebox.askyesno("Mark as imported",
                f"Record {len(originals)} file(s) from "
                f"'{m.get('tech')}/{m.get('name')}' as already in OD?\n\n"
                "Future audits will not re-flag them. No files are copied.",
                parent=dlg):
                return
            for opt in pics_options:
                try:
                    _append_sp_manifest_originals(opt["path"], originals)
                except Exception:
                    pass
            # Update local state so the row reflects the change
            m["new_count"] = 0
            m["new_names"] = set()
            ms = m.get("match_stats")
            if ms:
                ms["name"] = ms.get("total", len(originals))
                ms["new"] = 0
            try:
                show_toast(self,
                    f"Marked {len(originals)} as in OD — "
                    "re-audit to refresh the row count.",
                    kind="success")
            except Exception:
                pass
            # Subtract from the audit row's visible count too. The
            # parent audit row is refreshed in place once the dialog
            # closes — the <Destroy> handler reads _did_modify and
            # calls on_close_changed.
            r["sharepoint_new"] = max(0, r.get("sharepoint_new", 0) - len(originals))
            _did_modify[0] = True
            dlg.destroy()

        # ── Bulk action handlers ────────────────────────────────────
        # Each iterates selected matches and applies the per-match
        # action. Single up-front confirmation replaces the per-row
        # confirms so a 5-folder bulk op is one click + one OK.

        def _bulk_open():
            sel = _selected_matches()
            if not sel:
                return
            if len(sel) > 5 and not messagebox.askyesno(
                    "Open many?",
                    f"Open {len(sel)} folders in Explorer?\n\n"
                    f"That's a lot of windows.",
                    parent=dlg):
                return
            for m in sel:
                p = m.get("path")
                if p:
                    try:
                        os.startfile(p)
                    except Exception:
                        pass

        def _bulk_run_doc():
            sel = _selected_matches()
            if not sel:
                return
            run_docs = [m.get("run_doc_path") for m in sel
                         if m.get("run_doc_path")]
            run_docs = list(dict.fromkeys(run_docs))  # dedup, preserve order
            if not run_docs:
                messagebox.showinfo("No run docs",
                    "None of the selected folders have a linked daily "
                    "run doc to open.", parent=dlg)
                return
            if len(run_docs) > 3 and not messagebox.askyesno(
                    "Open many?",
                    f"Open {len(run_docs)} run docs?",
                    parent=dlg):
                return
            for rp in run_docs:
                try:
                    os.startfile(rp)
                except Exception:
                    pass

        def _bulk_mark_in_od():
            sel = _selected_matches()
            if not sel:
                return
            total_files = sum(len(m.get("files") or m.get("filenames") or [])
                              for m in sel)
            if not messagebox.askyesno("Mark selected as in OD",
                f"Mark {len(sel)} folder(s) ({total_files} files total) "
                f"as already in OD?\n\n"
                "Future audits will not re-flag these files. No files "
                "are copied.",
                parent=dlg):
                return
            marked = 0
            for m in sel:
                originals = [n for (n, _fp) in (m.get("files") or [])]
                if not originals:
                    originals = sorted(m.get("filenames") or set())
                if not originals:
                    continue
                for opt in pics_options:
                    try:
                        _append_sp_manifest_originals(opt["path"], originals)
                    except Exception:
                        pass
                m["new_count"] = 0
                m["new_names"] = set()
                ms = m.get("match_stats")
                if ms:
                    ms["name"] = ms.get("total", len(originals))
                    ms["new"] = 0
                marked += len(originals)
            try:
                show_toast(self,
                    f"Marked {marked} files as in OD across "
                    f"{len(sel)} folders — re-audit to refresh.",
                    kind="success")
            except Exception:
                pass
            r["sharepoint_new"] = max(
                0, sum(m.get("new_count", 0)
                       for m in (r.get("sharepoint_matches") or [])))
            _did_modify[0] = True
            _build_match_rows()

        def _bulk_reject():
            sel = _selected_matches()
            if not sel:
                return
            # Skip pinned overrides — rejecting an override is meaningless;
            # the user should unpin instead. Tell them so.
            override_paths = [m.get("path") for m in sel if m.get("override")]
            sel = [m for m in sel if not m.get("override")]
            if not sel:
                messagebox.showinfo("Nothing to reject",
                    "Selected rows are all user-pinned overrides — use "
                    "× Unpin on the row instead.", parent=dlg)
                return
            if not messagebox.askyesno("Mark selected as wrong job",
                f"Hide {len(sel)} folder(s) from {r['client']}'s "
                f"SharePoint matches?\n\n"
                "Future audits will skip them. You can undo with "
                "\"↩ Show rejected\" at the bottom of this dialog.",
                parent=dlg):
                return
            for m in sel:
                path = m.get("path")
                if path:
                    persistence.add_sp_match_reject(r["client"], path)
            try:
                show_toast(self,
                    f"Hidden {len(sel)} folder(s) from {r['client']} "
                    "matches.", kind="info")
            except Exception:
                pass
            if override_paths:
                try:
                    show_toast(self,
                        f"Skipped {len(override_paths)} pinned "
                        "override(s) — use Unpin to remove those.",
                        kind="warning")
                except Exception:
                    pass
            _did_modify[0] = True
            _build_match_rows()

        def _bulk_copy():
            sel = _selected_matches()
            if not sel:
                return
            with_new = [m for m in sel if m.get("new_count", 0) > 0]
            if not with_new:
                messagebox.showinfo("Nothing to copy",
                    "Selected folders have no new files to copy "
                    "(everything is already in OD).", parent=dlg)
                return
            total_new = sum(m.get("new_count", 0) for m in with_new)
            if not messagebox.askyesno("Copy selected",
                f"Copy {total_new} new file(s) from {len(with_new)} "
                f"folder(s) into the chosen PICS destination?",
                parent=dlg):
                return
            # Single match: just hand off to the existing copy path.
            # Multi: chain calls so progress lands one folder at a time
            # — _copy_match disables copy_buttons during the run, but
            # it doesn't block our own thread, so we serialize here by
            # just calling sequentially (each spawns its own thread but
            # the user-visible status reflects the active one).
            for m in with_new:
                try:
                    _copy_match(m)
                except Exception:
                    pass

        def _build_match_rows():
            # Tear down any existing rows + buttons before rebuilding.
            for child in list_card.winfo_children():
                try: child.destroy()
                except Exception: pass
            copy_buttons.clear()
            # Selection vars are owned per-row and rebuilt below, so
            # clear the dict to stop bulk actions from firing on stale
            # paths whose rows just got destroyed.
            match_select_vars.clear()

            # Substring search is loose — "Aldana" matches "Maldanado" — so
            # respect any per-client rejections the user has marked. Keep
            # rejections out of the visible list AND out of the audit row's
            # +N count so the match list reflects reality.
            rejected = persistence.get_sp_match_rejects(r["client"])
            all_matches = r.get("sharepoint_matches") or []
            current_matches = [
                m for m in all_matches if m.get("path") not in rejected]
            r["sharepoint_matches"] = current_matches
            r["sharepoint_new"] = sum(m.get("new_count", 0)
                                      for m in current_matches)

            summary_var.set(
                f"Found {len(current_matches)} SharePoint folder(s) matching "
                f'"{r["client"]}":')

            for m in current_matches:
                _build_one_match_row(m)

            # Selection just changed (rows torn down + rebuilt) — refresh
            # bulk-button labels and enable state to match the new set.
            _refresh_bulk_state()

        def _build_one_match_row(m):
            # outer = vertical container so we can add a sub-line below
            # the main row showing the run-doc activity for this folder.
            # The existing widgets all pack into `row` (the top line);
            # `sub` is added at the end of this function only when
            # there's activity info to render.
            outer = tk.Frame(list_card, bg=WHITE, padx=10, pady=4)
            outer.pack(fill="x")
            row = tk.Frame(outer, bg=WHITE)
            row.pack(fill="x")
            tag = "✓ matches run date" if m.get("matches_date") else ""
            new_count = m.get("new_count", 0)
            new_part = f"  ·  +{new_count} new" if new_count else "  ·  all in OD"
            folder_date = m.get("folder_date", "")
            date_part = f"  ·  📅 {folder_date}" if folder_date else ""
            stage_sub = m.get("stage_subfolder", "")
            stage_part = f"  ·  → {stage_sub}" if stage_sub else "  ·  → (PICS root)"

            # Per-row select checkbox — drives the bulk toolbar above.
            sel_var = tk.BooleanVar(value=False)
            match_select_vars[m["path"]] = sel_var
            tk.Checkbutton(row, variable=sel_var, bg=WHITE,
                           activebackground=WHITE, selectcolor=WHITE,
                           command=_refresh_bulk_state
                           ).pack(side="left", padx=(0, 4))

            # User-pinned overrides get a small 📌 badge before the
            # tech/name so it's obvious they're manual additions.
            if m.get("override"):
                tk.Label(row, text="📌", font=("Segoe UI Emoji", 9),
                         bg=WHITE, fg=LINK_FG
                         ).pack(side="left", padx=(0, 2))

            tk.Label(row,
                     text=f"{m['tech']} / {m['name']}",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_DARK, anchor="w"
                     ).pack(side="left")
            tk.Label(row,
                     text=f"  ·  {m['count']} files{new_part}{date_part}{stage_part}  {tag}",
                     font=("Segoe UI Variable", 8),
                     bg=WHITE,
                     fg=("#A6772A" if new_count else TEXT_GRAY),
                     anchor="w"
                     ).pack(side="left")

            # Per-row quick-look buttons — icon-only to keep the row
            # compact. Bulk toolbar above handles multi-select; per-row
            # icons are for "I just want this one folder right now".
            # Pack right-to-left so the visual order (left → right) is
            # 📥 Copy · 📄 Run · ❓ Why · 📁 Open · × Unpin, mirroring
            # the bulk toolbar's order.

            def _icon_btn(parent, icon, fg, active_bg, cmd, tip=None):
                btn = tk.Button(parent, text=icon,
                                font=("Segoe UI Variable", 11), bg=WHITE, fg=fg,
                                activebackground=active_bg,
                                relief="flat", padx=4, pady=0,
                                cursor="hand2", command=cmd, bd=0)
                if tip:
                    # Bare-bones hover tooltip — pops a small Toplevel
                    # 28px below the cursor and tears it down on leave.
                    # No third-party dep, no shared class needed (only
                    # used here), still gives discoverability for what
                    # each icon does.
                    tip_win = [None]
                    def _show(_e):
                        if tip_win[0] is not None:
                            return
                        try:
                            tw = tk.Toplevel(btn)
                            tw.wm_overrideredirect(True)
                            x = btn.winfo_rootx() + btn.winfo_width() + 4
                            y = btn.winfo_rooty()
                            tw.wm_geometry(f"+{x}+{y}")
                            tk.Label(tw, text=tip, font=("Segoe UI Variable", 8),
                                     bg=SURFACE_2, fg=TEXT_DARK,
                                     padx=6, pady=2).pack()
                            tip_win[0] = tw
                        except tk.TclError:
                            tip_win[0] = None
                    def _hide(_e=None):
                        tw = tip_win[0]
                        if tw is not None:
                            try: tw.destroy()
                            except tk.TclError: pass
                            tip_win[0] = None
                    btn.bind("<Enter>", _show)
                    btn.bind("<Leave>", _hide)
                    btn.bind("<ButtonPress-1>", _hide)
                return btn

            # Unpin sits on the FAR right (most destructive of the
            # row-level actions) — only for pinned overrides.
            if m.get("override"):
                _icon_btn(row, "×", "#A04025", "#FBEAE5",
                          lambda mm=m: _unpin_match(mm),
                          tip="Unpin this folder"
                          ).pack(side="right", padx=(2, 0))
            # 📁 Open in Explorer.
            _icon_btn(row, "📁", TEXT_DARK, "#E8F5EE",
                      lambda p=m["path"]: os.startfile(p),
                      tip="Open in Explorer"
                      ).pack(side="right", padx=(2, 0))
            # ❓ Why? — diagnostic.
            _icon_btn(row, "❓", "#666666", "#EEEEEE",
                      lambda mm=m: self._show_match_diagnostic(r, mm),
                      tip="Why did this folder match?"
                      ).pack(side="right", padx=(2, 0))
            # 📄 Run doc.
            run_doc = m.get("run_doc_path")
            if run_doc:
                _icon_btn(row, "📄", "#2C6FA8", "#EAF3FB",
                          lambda rp=run_doc: os.startfile(rp),
                          tip="Open the daily run doc"
                          ).pack(side="right", padx=(2, 0))
            # 📥 Copy this one folder. Only when there's something to
            # copy — bulk toolbar still handles multi-folder runs.
            if new_count > 0:
                _icon_btn(row, "📥", GREEN_DARK, "#DAF1E2",
                          lambda mm=m: _copy_match(mm),
                          tip=f"Copy +{new_count} new"
                          ).pack(side="right", padx=(2, 0))

            # Sub-line: what was done that day per the run-doc.
            # Resolved by parsing the run-doc for this folder's date
            # and matching this audit row's client. Empty when there's
            # no matching run-doc entry — we just don't render the
            # second line in that case so rows without context stay
            # compact.
            try:
                activity_summary = _activity_from_run_doc(
                    m.get("folder_date") or "", r.get("client") or "")
            except Exception:
                activity_summary = ""
            if activity_summary:
                sub = tk.Frame(outer, bg=WHITE)
                sub.pack(fill="x", padx=(28, 0))
                tk.Label(sub,
                          text=f"↳ Run-doc: {activity_summary}",
                          font=("Segoe UI Variable", 8, "italic"),
                          bg=WHITE, fg=GREEN_DARK, anchor="w"
                          ).pack(side="left")

        # Initial render of the match list. Re-callable on refresh.
        _build_match_rows()

        # Bottom action bar — Refresh + Close + manifest reset. The reset
        # wipes `.sharepoint_imported.json` at every PICS variant so the
        # next audit re-evaluates every photo (useful after a wrong import,
        # or to test that fresh diff behavior).
        bot = tk.Frame(wf, bg=BG)
        bot.pack(fill="x")

        def _clear_history():
            n = sum(_clear_sp_manifest(opt["path"]) for opt in pics_options)
            try:
                show_toast(self,
                    f"Cleared import history ({n} entries) — "
                    "re-audit to refresh.",
                    kind="info")
            except Exception:
                pass
            dlg.destroy()

        # Re-walk OD + SharePoint for this one job and rebuild the rows
        # in place. Runs in a background thread so the network walk
        # doesn't block the UI; the list updates when the scan finishes.
        refresh_btn = [None]
        def _do_refresh():
            if refresh_btn[0]:
                try:
                    refresh_btn[0].config(state="disabled", text="🔄 Refreshing…")
                except Exception:
                    pass
            status_var.set("Re-scanning OD + SharePoint…")

            def _bg():
                try:
                    self._rescan_sharepoint_for_result(r, self.run_date)
                    err = None
                except Exception as ex:
                    err = str(ex)

                def _done():
                    status_var.set(
                        "Refresh failed: " + err if err else "")
                    if not err:
                        # Rebuild diagnostic + match rows from updated r.
                        _refresh_diagnostic()
                        # pics_options may have changed if a new variant
                        # appeared — refresh the destination dropdown too.
                        new_opts = r.get("pics_options") or []
                        if new_opts:
                            pics_options.clear()
                            pics_options.extend(new_opts)
                            new_map = {
                                f"{o['label']}  ({o['count']} files)": o["path"]
                                for o in pics_options
                            }
                            dest_label_to_path.clear()
                            dest_label_to_path.update(new_map)
                            try:
                                dest_cb.config(values=list(new_map.keys()))
                                if dest_var.get() not in new_map:
                                    dest_var.set(next(iter(new_map.keys()), ""))
                                _on_dest_change()
                            except tk.TclError:
                                pass
                        _build_match_rows()
                        # Bubble updated counts to the audit row badge.
                        if self._last_results:
                            try:
                                self._render(self._last_results, None)
                            except Exception:
                                pass
                    if refresh_btn[0]:
                        try:
                            refresh_btn[0].config(state="normal", text="🔄 Refresh")
                        except Exception:
                            pass
                self.after(0, _done)

            threading.Thread(target=_bg, daemon=True).start()

        refresh_btn[0] = tk.Button(bot, text="🔄 Refresh",
                  font=("Segoe UI Variable", 8, "bold"),
                  bg=SUCCESS_BG, fg=SUCCESS_FG,
                  activebackground=SUCCESS_HOVER,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=_do_refresh)
        refresh_btn[0].pack(side="left", padx=(6, 0))

        # "+ Pin folder" — manual override for jobs the auto-matcher
        # missed. Opens a dir picker rooted at the SharePoint photos
        # share so the user can attach an arbitrary folder to this
        # client; the pin persists across audits.
        tk.Button(bot, text="📌 Pin folder…",
                  font=("Segoe UI Variable", 8, "bold"),
                  bg=LINK_BG, fg=LINK_FG,
                  activebackground=LINK_HOVER,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=_pin_folder
                  ).pack(side="left", padx=(6, 0))

        tk.Button(bot, text="🗑 Clear import history",
                  font=("Segoe UI Variable", 8),
                  bg=WHITE, fg=TEXT_GRAY,
                  activebackground=DANGER_HOVER,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=_clear_history
                  ).pack(side="left", padx=(6, 0))

        # "Show rejected" — un-hides anything the user marked as wrong job
        # for this client. Only relevant if there's something to restore,
        # so the button hides itself when the reject list is empty.
        restore_var = tk.StringVar()
        restore_btn = tk.Button(bot, textvariable=restore_var,
                  font=("Segoe UI Variable", 8),
                  bg=WHITE, fg=TEXT_GRAY,
                  activebackground=INFO_HOVER,
                  relief="flat", padx=10, pady=4, cursor="hand2")

        def _refresh_restore_btn():
            n = len(persistence.get_sp_match_rejects(r["client"]))
            if n:
                restore_var.set(f"↩ Show rejected ({n})")
                if not restore_btn.winfo_ismapped():
                    restore_btn.pack(side="left", padx=(6, 0))
            else:
                if restore_btn.winfo_ismapped():
                    restore_btn.pack_forget()

        def _restore_rejected():
            persistence.clear_sp_match_rejects(r["client"])
            # Refresh has to come from server-side data (the in-memory
            # r["sharepoint_matches"] was already filtered down). Re-walk
            # OD + SharePoint so the dropped matches reappear.
            _do_refresh()
            _refresh_restore_btn()

        restore_btn.config(command=_restore_rejected)
        _refresh_restore_btn()

        # Wrap _build_match_rows so the restore button stays in sync.
        _orig_build_match_rows = _build_match_rows
        def _build_match_rows_wrapped():
            _orig_build_match_rows()
            _refresh_restore_btn()
        _build_match_rows = _build_match_rows_wrapped

        tk.Button(bot, text="Close", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                  padx=12, pady=4,
                  command=dlg.destroy).pack(side="right")

    def _open_notes_dialog(self, client, path=None):
        """Open the Job Notes panel for this client.

        Migrates any legacy persistence-backed note into the .md store on first
        access, then navigates to the Job Notes panel (or spawns it standalone
        if not embedded in the launcher).
        """
        # Derive year from the audit result path; falls back to today's year.
        year = extract_job_year(path)

        # One-time migration: persistence note → %APPDATA%\…\notes\<year>\<client>.md
        legacy = persistence.get_note(client)
        if legacy and legacy.strip():
            try:
                from job_notes_gui import migrate_legacy_note
                # No clear_legacy callback — the legacy notes bucket in
                # state.json is now read-only fallback (via get_note /
                # has_note). Leaving the stale entry costs nothing and
                # removes the only writer of persistence.set_note.
                migrated = migrate_legacy_note(year, client, legacy)
                if migrated and self._last_results:
                    # Refresh the badge so the "📝" indicator stays accurate
                    self._render(self._last_results, None)
            except Exception:
                pass

        # Navigate (embedded mode → swap panel; standalone → spawn subprocess).
        self.navigate_to("job_notes", f"--year={year}", f"--client={client}")

    def _attach_inprogress_checklist(self, parent, client):
        """Render the IN PROGRESS - ADMIN Trello checklist inline at the
        bottom of an audit card — a checkbox per item that writes back to
        Trello on toggle. Loads in a background thread so the audit render
        never blocks on the network; a per-session cache keyed by card_id
        avoids re-fetching every time the virtualized card scrolls back
        into view. No-op when the client has no pinned Trello card."""
        try:
            pinned = persistence.get_trello_card_ids(client) or []
        except Exception:
            pinned = []
        if not pinned:
            return
        card_id = pinned[0]

        wrap = tk.Frame(parent, bg=WHITE)
        wrap.pack(fill="x", padx=10, pady=(2, 6))
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x", pady=(0, 3))
        hdr = tk.Label(wrap, text="🗂 In Progress — loading…",
                       font=("Segoe UI Variable", 8, "bold"),
                       bg=WHITE, fg=TEXT_GRAY, anchor="w")
        hdr.pack(anchor="w")
        items_frame = tk.Frame(wrap, bg=WHITE)
        items_frame.pack(fill="x")

        cache = getattr(self, "_inprog_cache", None)
        if cache is None:
            cache = self._inprog_cache = {}

        def _toggle(item_id, var):
            new_state = "complete" if var.get() else "incomplete"
            def _bg():
                ok = False
                try:
                    import trello_client as _tc
                    ok = bool(_tc.set_check_item_state(
                        card_id, item_id, new_state))
                except Exception:
                    ok = False
                def _done():
                    if not ok:
                        try:
                            var.set(not var.get())
                        except tk.TclError:
                            pass
                    else:
                        # Keep the session cache in sync so a scroll-away /
                        # back doesn't flash the old state.
                        entry = cache.get(card_id)
                        if entry:
                            for it in entry.get("checkItems") or []:
                                if it.get("id") == item_id:
                                    it["state"] = new_state
                try:
                    self.after(0, _done)
                except tk.TclError:
                    pass
            threading.Thread(target=_bg, daemon=True).start()

        def _render(checklist):
            try:
                if not hdr.winfo_exists():
                    return
            except tk.TclError:
                return
            if not checklist:
                hdr.config(text="🗂 In Progress (no checklist on card)")
                return
            hdr.config(text="🗂 In Progress")
            for item in (checklist.get("checkItems") or []):
                done = (item.get("state") or "").lower() == "complete"
                var = tk.BooleanVar(value=done)
                cb = tk.Checkbutton(
                    items_frame, text=item.get("name") or "?",
                    variable=var, bg=WHITE, fg=TEXT_DARK,
                    activebackground=WHITE, selectcolor=WHITE,
                    anchor="w", font=("Segoe UI Variable", 8),
                    command=lambda i=item.get("id"), v=var: _toggle(i, v))
                cb.pack(anchor="w", padx=6)

        # Cached → render immediately, no network.
        if card_id in cache:
            _render(cache[card_id])
            return

        def _fetch():
            checklist = None
            try:
                import trello_client as _tc
                card = _tc.get_card(card_id, actions_limit=0)
                for c in (card.get("checklists") or []) if card else []:
                    if (c.get("name") or "").strip().lower() == \
                            "in progress - admin":
                        checklist = c
                        break
            except Exception:
                checklist = None
            if checklist is not None:
                cache[card_id] = checklist
            try:
                self.after(0, lambda: _render(checklist))
            except tk.TclError:
                pass
        threading.Thread(target=_fetch, daemon=True).start()

    def _attach_card_context_menu(self, card, r):
        """Right-click on a card → shared client-card menu (Change folder,
        clear saved path/commercial, reset all memory). Refreshes ONLY
        this card after a folder change — full audit re-render would
        wipe and redraw every other row, which is slow and disorienting
        when only one job's folder changed.
        """
        attach_card_context_menu(
            self, [card], r["client"],
            run_date=self.run_date,
            audit_base=AUDIT_BASE,
            on_change_folder=lambda _p, c=r["client"]:
                self._refresh_single_card(c))

    def _export_pdf(self):
        if not self._last_results:
            messagebox.showerror("No Results", "Run an audit first.")
            return
        audit_export.open_export_window(self, self._last_results, self.run_date)

    def _open_flag_missing_for_row(self, client, card_id=""):
        """Pop the shared "Flag missing item" dialog scoped to one
        audit row. Same dialog the IUQ row and Snapshot nav use —
        keeps the affordance shape consistent across all three tools.
        `stage="audit"` so Hygiene attributes the gap to the daily
        audit step.
        """
        client = (client or "").strip()
        if not client:
            return
        # Auto-resolve the pinned card_id if the caller didn't pass
        # one — keeps the call site simple and matches the IUQ + APA
        # pattern (caller provides what it has, we fill in the rest).
        if not card_id:
            try:
                card_id = persistence.get_trello_card_id(client) or ""
            except Exception:
                card_id = ""
        tech_initials = ""
        if isinstance(self._last_results, list):
            for r in self._last_results:
                if (r.get("client") or "").strip() == client:
                    tech_initials = (r.get("tech_initials")
                                       or r.get("tech") or "").strip()
                    break
        try:
            from flag_missing_dialog import open_flag_dialog
        except Exception as ex:
            messagebox.showerror("Flag dialog unavailable",
                                   f"Couldn't load module:\n{ex}",
                                   parent=self)
            return
        open_flag_dialog(
            self,
            client=client,
            card_id=card_id,
            card_url=(f"https://trello.com/c/{card_id}"
                      if card_id else ""),
            tech_initials=tech_initials,
            stage="audit",
        )

    def _copy_xa_apology_note(self):
        """Copy the standard XA apology text to the clipboard. Mirrors
        the Hygiene panel's xa_apology section button so the same
        wording is one click away from both surfaces. Single source of
        truth in ar_followup.DEFAULT_NOTE."""
        try:
            from ar_followup import DEFAULT_NOTE as _note
        except Exception:
            _note = ("Our apologies for the delay. Please note our "
                     "estimating team is diligently working on the file.")
        try:
            self.clipboard_clear()
            self.clipboard_append(_note)
            self.update()
        except tk.TclError:
            return
        try:
            show_toast(self, "📋 Copied XA apology note", kind="success")
        except Exception:
            pass

    def _push_new_losses_to_apa(self):
        """Take today's new-loss jobs from the most recent audit and append
        them as Initial Uploads rows in today's APA doc, status=pending.
        Skips clients already present in any section of today's doc."""
        if not self._last_results:
            messagebox.showerror("No Results", "Run an audit first.",
                                  parent=self)
            return
        new_losses = [r for r in self._last_results if r.get("new_loss")]
        if not new_losses:
            show_toast(self, "No new-loss jobs in this audit.", kind="info")
            return

        items = [(r.get("client", ""), self._carrier_for_result(r))
                 for r in new_losses]

        try:
            import apa_monitor_gui
            added, skipped = apa_monitor_gui.push_initial_uploads(items)
        except Exception as ex:
            messagebox.showerror("Couldn't push to APA",
                                  f"{ex}", parent=self)
            return

        if added and skipped:
            show_toast(self,
                f"Pushed {len(added)} to APA · {len(skipped)} already present",
                kind="success")
        elif added:
            show_toast(self, f"Pushed {len(added)} new losses to APA",
                       kind="success")
        else:
            show_toast(self,
                f"All {len(skipped)} new losses already in today's APA",
                kind="info")

    def _post_daily_misses_to_trello(self):
        """For each flagged job in the current audit, post a daily-miss
        request comment via `missing_items_tracker.capture_missing_items`.

        The tracker handles deduplication + escalation:
          • 1st request day → standard request comment with the tech
            @mention
          • 2nd+ request day → escalation comment that also tags
            @ZAC + @SAM
        The 12-hour cooldown inside the tracker prevents quick re-runs
        from inflating the request count.

        Best-effort: jobs with no pinned Trello card are silently
        skipped (no way to post a comment without one)."""
        if not self._last_results:
            messagebox.showerror("No Results", "Run an audit first.",
                                  parent=self)
            return
        flagged = [r for r in self._last_results if r.get("flagged")]
        if not flagged:
            show_toast(self, "No flagged jobs to chase — every row is clean.",
                       kind="info")
            return
        if not messagebox.askyesno(
                "Post daily misses",
                f"Post / escalate Trello comments for {len(flagged)} "
                "flagged job(s) from this audit?\n\n"
                "Each card will get a comment listing its outstanding "
                "items. Cards already commented on within the last "
                "12 hours are skipped.",
                parent=self):
            return
        try:
            import missing_items_tracker as mit
        except Exception as ex:
            messagebox.showerror("Tracker unavailable", str(ex),
                                  parent=self)
            return
        posted = 0
        skipped_no_card = 0
        skipped_no_misses = 0
        for r in flagged:
            client = (r.get("client") or "").strip()
            if not client:
                continue
            try:
                card_id = persistence.get_trello_card_id(client) or ""
            except Exception:
                card_id = ""
            if not card_id:
                skipped_no_card += 1
                continue
            # Pull form-side gaps from the audit row + derive photo
            # gaps from the issues list. The tracker canonicalizes
            # the labels, so passing through audit-style strings is
            # fine.
            missing: list[str] = []
            for issue in (r.get("form_issues") or []):
                if issue and str(issue) not in missing:
                    missing.append(str(issue))
            for label in (r.get("missing_items") or []):
                if label and label not in missing:
                    missing.append(label)
            # Also derive from the checklist: any row whose
            # 'photos' / 'forms' bucket lists outstanding items.
            for k, v in (r.get("checklist") or {}).items():
                if v == "missing" and k not in missing:
                    missing.append(k)
            if not missing:
                skipped_no_misses += 1
                continue
            tech_initials = (r.get("tech_initials")
                             or r.get("tech") or "").strip()
            try:
                mit.capture_missing_items(
                    client, card_id=card_id,
                    card_url=f"https://trello.com/c/{card_id}",
                    missing=missing,
                    tech_initials=tech_initials,
                )
                posted += 1
            except Exception:
                pass
        summary_bits = [f"{posted} comment(s) posted"]
        if skipped_no_card:
            summary_bits.append(f"{skipped_no_card} skipped (no card pinned)")
        if skipped_no_misses:
            summary_bits.append(
                f"{skipped_no_misses} skipped (no specific misses)")
        show_toast(self, " · ".join(summary_bits), kind="success",
                   duration=4000)

    # ── Escalation helper ──────────────────────────────────────────────

    _ESCALATION_ROLES = ("Sam", "Zac", "George")

    def _carrier_for_result(self, r):
        """Title-cased carrier name from r["path"]/EMS, or None if undetected
        or the path can't be read. Shared by APA push and escalation."""
        path = r.get("path") or ""
        if not path:
            return None
        try:
            c = detect_carrier_from_ems(os.path.join(path, "EMS"))
        except Exception:
            return None
        return c.title() if c else None

    def _format_escalation_message(self, r):
        """Build the escalation body per the duties doc: current status,
        last contact, what we're waiting on, recommended next step.

        Includes the matching Trello card link when the client is
        pinned (or fuzzy-search returns one). Recipients can click
        straight through to the card from Teams."""
        client = r.get("client") or "this job"
        aging = int(r.get("aging") or 0)
        last = r.get("last")
        last_str = last.strftime("%m/%d/%y") if last else "no recent activity"
        carrier = self._carrier_for_result(r) or ""

        waiting = []
        for fi in (r.get("form_issues") or []):
            waiting.append(fi)
        for pi in (r.get("photo_issues") or []):
            waiting.append(pi)
        for ni in (r.get("note_issues") or []):
            waiting.append(ni)

        # Pinned cards take priority; fall back to fuzzy lookup so
        # un-pinned clients still get a usable link in the message.
        # Network errors degrade silently — a missing link is far
        # better than a dialog that hangs on Trello latency.
        trello_urls = []
        try:
            import trello_client
            pinned = persistence.get_trello_card_ids(client)
            if pinned:
                trello_urls = [f"https://trello.com/c/{cid}" for cid in pinned]
            else:
                fallback = trello_client.card_url_for_client(client)
                if fallback:
                    trello_urls = [fallback]
        except Exception:
            pass

        lines = []
        header = f"Escalation: {client}"
        if carrier:
            header += f" — {carrier}"
        lines.append(header)
        lines.append("")
        lines.append(f"Status: flagged ({aging} business days inactive)")
        lines.append(f"Last activity: {last_str}")
        if waiting:
            lines.append("Waiting on:")
            for w in waiting:
                lines.append(f"  • {w}")
        else:
            lines.append("Waiting on: (no missing items — see notes)")
        if trello_urls:
            lines.append("")
            label = ("Trello cards:" if len(trello_urls) > 1
                     else "Trello card:")
            lines.append(label)
            for u in trello_urls:
                lines.append(f"  {u}")
        lines.append("")
        if aging >= 10:
            lines.append("Recommended: 10+ days no movement — please advise.")
        else:
            lines.append("Recommended: please follow up with the PM/tech.")
        return "\n".join(lines)

    def _open_escalation_dialog(self, r, on_marked=None):
        """Modal: pick a recipient, edit the message, send via Teams or copy.
        `on_marked(escalated_bool)` fires whenever the persistence flag flips
        so the caller (the 🚩 button) can refresh its color in-place."""
        try:
            from apa_monitor_gui import open_teams_chat
        except Exception:
            open_teams_chat = None

        client = r.get("client") or ""
        aging = int(r.get("aging") or 0)
        default_role = "George" if aging >= 10 else "Sam"

        dlg = tk.Toplevel(self)
        dlg.title(f"Escalate — {client}")
        dlg.configure(bg=BG)
        dlg.geometry("560x460")
        try:
            dlg.transient(self)
            dlg.grab_set()
        except Exception:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head,
                 text=f"Escalating: {client}   ({aging} biz days)",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 ).pack(anchor="w")

        # Recipient row
        role_row = tk.Frame(dlg, bg=BG, padx=14)
        role_row.pack(fill="x", pady=(0, 8))
        tk.Label(role_row, text="To:", bg=BG, fg=TEXT_DARK,
                 font=("Segoe UI Variable", 9)).pack(side="left")
        role_var = tk.StringVar(value=default_role)
        emails = persistence.get_escalation_emails()
        for role in self._ESCALATION_ROLES:
            email = emails.get(role, "")
            label = f"{role}" + (f"  ({email})" if email else "  (no email)")
            tk.Radiobutton(role_row, text=label, variable=role_var,
                            value=role, bg=BG, fg=TEXT_DARK,
                            activebackground=BG,
                            font=("Segoe UI Variable", 9)
                            ).pack(side="left", padx=(8, 0))

        # Message body
        body_row = tk.Frame(dlg, bg=BG, padx=14)
        body_row.pack(fill="both", expand=True, pady=(0, 8))
        text_w = tk.Text(body_row, font=("Segoe UI Variable", 10), wrap="word",
                         bg=WHITE, fg=TEXT_DARK,
                         relief="solid", bd=1, padx=8, pady=6)
        text_w.pack(fill="both", expand=True)
        text_w.insert("1.0", self._format_escalation_message(r))

        # Buttons
        btn_row = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        btn_row.pack(fill="x")

        mark_var = tk.BooleanVar(
            value=persistence.is_escalated(self.run_date, client))
        tk.Checkbutton(btn_row, text="Mark as escalated today",
                        variable=mark_var, bg=BG, fg=TEXT_DARK,
                        activebackground=BG,
                        font=("Segoe UI Variable", 9)
                        ).pack(side="left")

        def _persist_mark():
            persistence.set_escalated(self.run_date, client, mark_var.get())
            if on_marked is not None:
                try:
                    on_marked(mark_var.get())
                except Exception:
                    pass

        def _do_copy():
            txt = text_w.get("1.0", "end-1c")
            try:
                self.clipboard_clear()
                self.clipboard_append(txt)
                self.update()
            except tk.TclError:
                pass
            _persist_mark()
            show_toast(dlg, "Copied to clipboard", kind="success")

        def _do_teams():
            txt = text_w.get("1.0", "end-1c")
            role = role_var.get()
            email = persistence.get_escalation_email(role)
            if not email:
                messagebox.showwarning(
                    "No email saved",
                    f"No email saved for {role}. Open ⋯ More → "
                    f"Escalation contacts… to add one.",
                    parent=dlg)
                return
            ok = bool(open_teams_chat and open_teams_chat(email, txt))
            if not ok:
                messagebox.showerror(
                    "Couldn't open Teams",
                    "Failed to launch the Teams chat. "
                    "Use Copy and paste it in manually.",
                    parent=dlg)
                return
            _persist_mark()
            show_toast(self, f"Opened Teams chat to {role}", kind="success")
            dlg.destroy()

        tk.Button(btn_row, text="Close", command=dlg.destroy,
                   font=("Segoe UI Variable", 9), padx=10
                   ).pack(side="right")
        tk.Button(btn_row, text="Copy", command=_do_copy,
                   font=("Segoe UI Variable", 9), padx=10
                   ).pack(side="right", padx=(0, 6))
        tk.Button(btn_row, text="Open in Teams", command=_do_teams,
                   font=("Segoe UI Variable", 9, "bold"),
                   bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                   relief="flat", padx=12, pady=4
                   ).pack(side="right", padx=(0, 6))

    def _open_escalation_contacts_dialog(self):
        """Tiny dialog: edit emails for Sam/Zac/George."""
        dlg = tk.Toplevel(self)
        dlg.title("Escalation contacts")
        dlg.configure(bg=BG)
        dlg.geometry("420x220")
        try:
            dlg.transient(self)
            dlg.grab_set()
        except Exception:
            pass

        tk.Label(dlg,
                 text="Email per role — used by the 🚩 escalation button.",
                 font=("Segoe UI Variable", 9),
                 bg=BG, fg=TEXT_GRAY
                 ).pack(anchor="w", padx=14, pady=(12, 6))

        rows = tk.Frame(dlg, bg=BG, padx=14)
        rows.pack(fill="x")
        entries = {}
        for role in self._ESCALATION_ROLES:
            row = tk.Frame(rows, bg=BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=f"{role}:", width=8, anchor="w",
                     bg=BG, fg=TEXT_DARK,
                     font=("Segoe UI Variable", 9, "bold")
                     ).pack(side="left")
            ent = tk.Entry(row, font=("Segoe UI Variable", 9), bg=WHITE)
            ent.insert(0, persistence.get_escalation_email(role))
            ent.pack(side="left", fill="x", expand=True)
            entries[role] = ent

        def _save_and_close():
            for role, ent in entries.items():
                persistence.set_escalation_email(role,
                                                  ent.get().strip())
            dlg.destroy()
            show_toast(self, "Escalation contacts saved", kind="success")

        btn_row = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        btn_row.pack(fill="x", side="bottom")
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                   font=("Segoe UI Variable", 9), padx=10
                   ).pack(side="right")
        tk.Button(btn_row, text="Save",
                   command=_save_and_close,
                   font=("Segoe UI Variable", 9, "bold"),
                   bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                   relief="flat", padx=12, pady=4
                   ).pack(side="right", padx=(0, 6))

    def _archive_month_dialog(self):
        """Preview-and-confirm dialog for the SharePoint month archive.
        Defaults to last completed calendar month; the user can pick a
        different month via two spinners. Shows a tech-grouped list of
        the moves that will happen, then runs them in a background
        thread so the UI doesn't lock during the network rename pass."""
        from datetime import datetime as _dt
        try:
            from sharepoint import (plan_month_archive,
                                     apply_month_archive)
        except Exception as ex:
            messagebox.showerror("SharePoint not available",
                f"Could not import archive helpers: {ex}", parent=self)
            return

        today = _dt.today()
        # Default to the previous calendar month (1st of this month
        # minus 1 day = last day of previous month).
        prev_first_of_this = today.replace(day=1)
        last_month = prev_first_of_this - timedelta(days=1)
        default_year  = last_month.year
        default_month = last_month.month

        dlg = tk.Toplevel(self)
        dlg.title("Archive SharePoint folders")
        dlg.configure(bg=BG)
        dlg.geometry("560x520")
        try:
            dlg.transient(self)
        except Exception:
            pass
        dlg.grab_set()

        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="Archive month",
                 font=("Segoe UI Variable", 12, "bold"), bg=BG
                 ).pack(anchor="w")
        tk.Label(head,
                 text="Move every dated folder from the chosen month "
                      "into a `<MonthName YYYY>` archive under its "
                      "tech. Tech roots and already-archived folders "
                      "are skipped.",
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY,
                 wraplength=520, justify="left"
                 ).pack(anchor="w", pady=(2, 8))

        picker_row = tk.Frame(head, bg=BG)
        picker_row.pack(anchor="w", pady=(0, 4))
        tk.Label(picker_row, text="Month:",
                 font=("Segoe UI Variable", 9, "bold"), bg=BG
                 ).pack(side="left")
        month_var = tk.StringVar(value=_dt(default_year, default_month, 1)
                                       .strftime("%B"))
        year_var  = tk.StringVar(value=str(default_year))
        month_cb = ttk.Combobox(
            picker_row, textvariable=month_var, state="readonly",
            width=12,
            values=[_dt(2000, m, 1).strftime("%B") for m in range(1, 13)])
        month_cb.pack(side="left", padx=(6, 4))
        year_cb = ttk.Combobox(
            picker_row, textvariable=year_var, state="readonly", width=6,
            values=[str(today.year - i) for i in range(5)])
        year_cb.pack(side="left")

        # Plan list — populated on every "Preview" click and after the
        # initial default load.
        list_card = tk.Frame(dlg, bg=WHITE,
                              highlightthickness=1,
                              highlightbackground=BORDER)
        list_card.pack(fill="both", expand=True, padx=14, pady=(4, 4))
        scroll = ScrollableFrame(list_card, bg=WHITE, padx=8)
        scroll.pack(fill="both", expand=True)

        status_var = tk.StringVar(value="")
        status_lbl = tk.Label(dlg, textvariable=status_var,
                              font=("Segoe UI Variable", 9, "italic"),
                              bg=BG, fg=TEXT_GRAY,
                              wraplength=520, justify="left")
        status_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        # plan_state["vars"] is a list parallel to plan_state["plan"]
        # holding the per-row tk.BooleanVar so _do_archive can filter
        # out anything the user unchecked.
        plan_state = {"plan": [], "vars": [], "loading": False}

        def _render_plan(plan):
            for w in scroll.inner.winfo_children():
                try: w.destroy()
                except Exception: pass
            plan_state["vars"] = []
            if not plan:
                tk.Label(scroll.inner,
                         text="Nothing to archive for this month.",
                         font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_GRAY,
                         pady=20).pack()
                return
            # Group by tech for readability. Per-tech vars list lets the
            # tech-header checkbox toggle just that tech's rows.
            by_tech = {}
            for p in plan:
                by_tech.setdefault(p["tech"], []).append(p)
            for tech in sorted(by_tech.keys(), key=str.lower):
                tech_vars = []
                hdr = tk.Frame(scroll.inner, bg=WHITE)
                hdr.pack(fill="x", pady=(6, 2))
                tech_master = tk.BooleanVar(value=True)
                def _toggle_tech(tv=tech_master, sub=tech_vars):
                    new = tv.get()
                    for v in sub:
                        v.set(new)
                tk.Checkbutton(hdr, variable=tech_master, bg=WHITE,
                               activebackground=WHITE, selectcolor=WHITE,
                               command=_toggle_tech
                               ).pack(side="left")
                tk.Label(hdr,
                         text=f"{tech}  ({len(by_tech[tech])})",
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=WHITE, fg=TEXT_DARK, anchor="w"
                         ).pack(side="left")
                for p in by_tech[tech]:
                    var = tk.BooleanVar(value=True)
                    plan_state["vars"].append(var)
                    tech_vars.append(var)
                    row = tk.Frame(scroll.inner, bg=WHITE)
                    row.pack(fill="x")
                    tk.Checkbutton(row, variable=var, bg=WHITE,
                                   activebackground=WHITE,
                                   selectcolor=WHITE
                                   ).pack(side="left")
                    tk.Label(row, text=p["name"],
                             font=("Segoe UI Variable", 8), bg=WHITE,
                             fg=TEXT_DARK, anchor="w"
                             ).pack(side="left", fill="x", expand=True)

        def _toggle_all():
            """Flip every row checkbox — handy for inverting the default."""
            vars_ = plan_state["vars"]
            new = not (vars_ and all(v.get() for v in vars_))
            for v in vars_:
                v.set(new)

        def _load_plan():
            if plan_state["loading"]:
                return
            try:
                month_idx = (
                    [_dt(2000, m, 1).strftime("%B") for m in range(1, 13)]
                    .index(month_var.get())) + 1
                year = int(year_var.get())
            except Exception:
                status_var.set("Invalid month/year selection.")
                return
            plan_state["loading"] = True
            status_var.set("Scanning SharePoint…")

            def _bg():
                try:
                    plan = plan_month_archive(year, month_idx)
                except Exception as ex:
                    plan = None
                    err = str(ex)
                else:
                    err = None

                def _done():
                    plan_state["loading"] = False
                    if err:
                        status_var.set(f"Scan failed: {err}")
                        return
                    plan_state["plan"] = plan or []
                    _render_plan(plan_state["plan"])
                    n = len(plan_state["plan"])
                    status_var.set(
                        f"Found {n} folder(s) to move." if n
                        else "No folders match this month.")
                self.after(0, _done)

            threading.Thread(target=_bg, daemon=True).start()

        def _do_archive():
            full_plan = plan_state["plan"]
            vars_ = plan_state["vars"]
            if not full_plan:
                return
            # Only act on the rows the user left checked. Vars are in
            # render order, which matches plan order after the by-tech
            # grouping — `_render_plan` walks the same sort.
            sorted_plan = []
            by_tech = {}
            for p in full_plan:
                by_tech.setdefault(p["tech"], []).append(p)
            for tech in sorted(by_tech.keys(), key=str.lower):
                sorted_plan.extend(by_tech[tech])
            picked = [p for p, v in zip(sorted_plan, vars_) if v.get()]
            if not picked:
                messagebox.showinfo(
                    "Nothing selected",
                    "Check at least one folder before archiving.",
                    parent=dlg)
                return
            if not messagebox.askyesno(
                    "Confirm archive",
                    f"Move {len(picked)} folder(s) into their tech's "
                    f"{month_var.get()} {year_var.get()} archive?\n\n"
                    "This rewrites the live SharePoint share. "
                    "Folder paths users have memorized will change.",
                    parent=dlg):
                return
            status_var.set("Moving…")

            def _bg():
                try:
                    result = apply_month_archive(picked)
                except Exception as ex:
                    result = {"moved": [], "errors": [("?", str(ex))]}

                def _done():
                    moved  = result.get("moved", [])
                    errors = result.get("errors", [])
                    msg = (f"Moved {len(moved)} folder(s). "
                           f"{len(errors)} error(s).")
                    status_var.set(msg)
                    if errors:
                        # Show details inline so the user knows what
                        # failed without digging into ems.log.
                        first_err = errors[0]
                        messagebox.showwarning(
                            "Some moves failed",
                            f"{msg}\n\n"
                            f"First error:\n{first_err[1]}\n\n"
                            "See ems.log for the full list.",
                            parent=dlg)
                        for src, err in errors:
                            try:
                                import ems_log
                                ems_log.warn("archive_month",
                                    f"failed: {src}: {err}")
                            except Exception:
                                pass
                    # Re-scan so the list reflects what's left (in case
                    # the user wants to retry the failures).
                    _load_plan()
                self.after(0, _done)

            threading.Thread(target=_bg, daemon=True).start()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(fill="x", padx=14, pady=(0, 12))
        tk.Button(btn_row, text="Preview",
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=INFO_BG, fg=INFO_FG, activebackground=INFO_HOVER,
                  relief="flat", padx=12, pady=4, cursor="hand2",
                  command=_load_plan).pack(side="left")
        tk.Button(btn_row, text="Toggle All",
                  font=("Segoe UI Variable", 9),
                  bg=WHITE, fg=TEXT_DARK,
                  relief="flat", padx=12, pady=4, cursor="hand2",
                  command=_toggle_all).pack(side="left", padx=(8, 0))
        tk.Button(btn_row, text="Archive →",
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=12, pady=4, cursor="hand2",
                  command=_do_archive).pack(side="left", padx=(8, 0))
        tk.Button(btn_row, text="Close",
                  font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK,
                  relief="flat", padx=12, pady=4,
                  command=dlg.destroy).pack(side="right")

        # Auto-load the default-month plan on open.
        _load_plan()

    def _render_stale_banner(self, stale_jobs):
        """Mount a yellow banner above the audit list listing flagged
        jobs from the backlog that haven't been audited in 7+ days.
        Click → opens a modal listing them so they don't get forgotten
        just because they fell off the daily run-doc."""
        n = len(stale_jobs)
        wrap = tk.Frame(self._inner, bg=WARN_BG,
                        highlightbackground=WARN_HOVER,
                        highlightthickness=1)
        wrap.pack(fill="x", padx=6, pady=(2, 4))
        msg = (f"⏰  {n} flagged "
               f"job{'s' if n != 1 else ''} "
               f"haven't been audited in 7+ days")
        tk.Label(wrap, text=msg,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=WARN_BG, fg=WARN_FG, padx=10, pady=4
                 ).pack(side="left")

        def _open_dialog():
            dlg = tk.Toplevel(self)
            dlg.title("Stale Flagged Jobs")
            dlg.configure(bg=BG)
            dlg.geometry("520x420")
            try:
                dlg.transient(self)
            except Exception:
                pass
            dlg.grab_set()
            tk.Label(dlg,
                     text=f"{n} flagged job{'s' if n != 1 else ''} "
                          f"not audited in 7+ days",
                     font=("Segoe UI Variable", 11, "bold"),
                     bg=BG, padx=14, pady=10).pack(anchor="w")
            tk.Label(dlg,
                     text="These were flagged when last seen and "
                          "haven't been re-audited since. They may "
                          "have fallen off the daily run-doc but "
                          "still need attention.",
                     font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY,
                     wraplength=480, justify="left",
                     padx=14).pack(anchor="w", pady=(0, 8))
            scroll = ScrollableFrame(dlg, bg=BG, padx=8)
            scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            inner = scroll.inner
            for j in stale_jobs:
                row = tk.Frame(inner, bg=WHITE, padx=8, pady=4,
                               highlightbackground=BORDER,
                               highlightthickness=1)
                row.pack(fill="x", padx=2, pady=2)
                last = j.get("last_audited", "")
                try:
                    d = datetime.fromisoformat(last)
                    last_str = d.strftime("%m/%d/%y")
                    days_ago = (datetime.today() - d).days
                except Exception:
                    last_str = last[:10] if last else "?"
                    days_ago = "?"
                tk.Label(row, text=j.get("client", "?"),
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=WHITE, anchor="w"
                         ).pack(side="left", fill="x", expand=True)
                tk.Label(row,
                         text=f"last: {last_str} ({days_ago}d ago)",
                         font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY
                         ).pack(side="right", padx=(8, 0))
            btn_row = tk.Frame(dlg, bg=BG)
            btn_row.pack(side="bottom", fill="x", pady=(0, 8))
            tk.Button(btn_row, text="Close", font=("Segoe UI Variable", 9),
                      bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                      padx=14, pady=4, command=dlg.destroy
                      ).pack(side="right", padx=(4, 14))
            # "Audit these" button — re-runs the main audit on just the
            # stale-flagged clients (no run-doc context needed since the
            # audit only needs the insured name to find the folder).
            # Lets the user knock the backlog down without manually
            # typing each client into the single-job dialog.
            def _audit_stale():
                names = [j.get("client", "").strip()
                         for j in stale_jobs if (j.get("client") or "").strip()]
                if not names:
                    return
                dlg.destroy()
                self._audit_named_jobs(names, source_label="stale backlog")
            tk.Button(btn_row, text=f"🔍 Audit these ({n})",
                      font=("Segoe UI Variable", 9, "bold"),
                      bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                      relief="flat", padx=14, pady=4, cursor="hand2",
                      command=_audit_stale
                      ).pack(side="right", padx=4)

        tk.Button(wrap, text="View →",
                  font=("Segoe UI Variable", 8, "bold"),
                  bg=WARN_FG, fg=WHITE, activebackground=WARN_HOVER,
                  relief="flat", padx=10, pady=2, cursor="hand2",
                  command=_open_dialog
                  ).pack(side="right", padx=(0, 8), pady=4)

    def _render(self, results, err, *, expected_total=None,
                streaming=False):
        """Render the audit panel.

        Two modes:
          • Batch (default): pass the full results list and we render
            every card. Writes audit_md immediately.
          • Streaming (streaming=True, expected_total=N): we set up
            chrome and counters for an audit that's still in progress,
            stash a `_render_one_card(r)` closure on self for the
            worker thread to call as each result arrives, and DON'T
            write audit_md (the streaming finalize step does that).
        """
        # Clear any prior render. _run_audit / _audit_named_jobs already
        # clear before invoking us, but other callers (SP-match Refresh,
        # legacy-note migration, on_show with _pending_render) don't —
        # without this, a re-render appended a second full set of
        # section banners + cards on top of the first.
        self._virt_cards.clear()
        for w in self._inner.winfo_children():
            w.destroy()
        # Re-populating from scratch — the prior card-by-client map is
        # now stale (the widgets it referenced are destroyed). Reset so
        # `_refresh_single_card` lookups don't hit dangling Frame refs.
        self._card_by_client = {}

        if err:
            self.status_label.configure(text=f"Error: {err}")
            tk.Label(self._inner, text=f"⚠  {err}", font=("Segoe UI Variable", 10),
                     bg=BG, fg=FLAG_RED).pack(pady=20)
            return

        self._last_results = results
        # Defer audit_md write to the streaming finalize step — writing
        # at the start with a partial result set would clobber yesterday's
        # full audit log with mid-stream snapshots. Batch mode still
        # writes here so behavior matches the original.
        if not streaming:
            try:
                audit_export.write_audit_md(
                    results, run_date=self.run_date, source="Run Audit")
            except Exception:
                pass
        # Counters live in single-element boxes so the streaming render
        # path can mutate them as each card lands without `nonlocal`
        # gymnastics. _update_status reads from these boxes.
        if streaming:
            total_box   = [int(expected_total or 0)]
            flagged_box = [0]
            # Accumulator the streaming worker appends to; on finalize
            # this becomes self._last_results so SP refresh, export,
            # and re-render on panel-show all see the full set.
            self._streaming_results = []
        else:
            total_box   = [len(results)]
            flagged_box = [sum(1 for r in results if r["flagged"])]
        resolved = [0]

        # Repeat-offender data: pull audit_count per (folder, unit) once
        # so each row's badge lookup is a dict get, not a list scan. Built
        # before rendering rather than per-row to avoid hitting the JSON
        # backlog file N times.
        try:
            audit_count_idx = audit_export.get_audit_count_index()
        except Exception:
            audit_count_idx = {}

        # Stale-flagged-jobs banner: jobs that are flagged in the backlog
        # but haven't been audited in 7+ days. Surfaced ABOVE the column
        # header so it's the first thing the user sees if any.
        try:
            stale_jobs = audit_export.get_stale_flagged_jobs(days=7)
        except Exception:
            stale_jobs = []
        if stale_jobs:
            self._render_stale_banner(stale_jobs)

        def _update_status():
            total = total_box[0]
            flagged = flagged_box[0]
            rem = flagged - resolved[0]
            # Single status line: run date + counts. Replaces the separate
            # date_label that used to sit above and the prior status line
            # that omitted the date — one source of truth, one place to
            # look. In streaming mode total/flagged grow as cards land.
            date_part = f"{self.run_date}  ·  " if self.run_date else ""
            self.status_label.configure(
                text=f"{date_part}{total} jobs  ·  "
                     f"{rem} flagged  ·  "
                     f"{total - flagged + resolved[0]} OK")

        def _make_import_action(cp, var, lbl, all_v, bl, ca, cr,
                                  on_success=None, client_name=""):
            def _do():
                dlg = tk.Toplevel(self)
                dlg.title("Docusketch")
                dlg.resizable(False, False)
                dlg.grab_set()
                wf = tk.Frame(dlg, bg=BG, padx=20, pady=16)
                wf.pack()
                tk.Label(wf, text="Make sure the Docusketch zip was downloaded from:",
                         font=("Segoe UI Variable", 10), bg=BG).pack(anchor="w")
                _url = "https://app.docusketch.com/portal-cc/projects"
                lnk = tk.Label(wf, text=_url, font=("Segoe UI Variable", 9, "underline"),
                               bg=BG, fg=LINK_FG, cursor="hand2")
                lnk.pack(anchor="w", pady=(2, 10))
                lnk.bind("<Button-1>", lambda e: webbrowser.open(_url))
                tk.Label(wf, text="Confirm the zip is in your Downloads folder.",
                         font=("Segoe UI Variable", 10), bg=BG).pack(anchor="w", pady=(0, 8))

                def _request_via_trello():
                    try:
                        import docusketch_requests as dr
                        hit = dr.find_card_for_client(client_name)
                    except Exception as ex:
                        messagebox.showerror(
                            "Lookup failed",
                            f"Couldn't search Trello: {ex}",
                            parent=dlg)
                        return
                    if hit is None:
                        messagebox.showwarning(
                            "No card found",
                            f"Couldn't find a Trello card for "
                            f"'{client_name}'. Open the card manually "
                            f"and post '{dr.DEFAULT_NOTE}'.",
                            parent=dlg)
                        return
                    entry = dr.request(hit["card_id"],
                                         client_name=client_name)
                    if entry is None:
                        messagebox.showerror(
                            "Couldn't record",
                            "Trello request failed. Check ems.log.",
                            parent=dlg)
                        return
                    msg = (f"Posted to {entry['card_name']}.\n"
                           f"It'll show in the Hygiene panel's "
                           f"'📐 Docusketch pending' section daily "
                           f"until you import the zip.")
                    if not entry.get("comment_posted", True):
                        msg = ("Recorded locally, but the Trello "
                               "comment failed to post. Open the "
                               "card and post manually.")
                    messagebox.showinfo("Docusketch requested",
                                          msg, parent=dlg)
                    dlg.destroy()

                _proceed = [False]
                def _ok(): _proceed[0] = True; dlg.destroy()
                br = tk.Frame(wf, bg=BG); br.pack(fill="x", pady=(4, 0))
                tk.Button(br, text="Cancel", font=("Segoe UI Variable", 9), bg=SURFACE_2,
                          fg=TEXT_DARK, relief="flat", padx=12, pady=4,
                          command=dlg.destroy).pack(side="left")
                if client_name:
                    tk.Button(br, text="📐 Mark Requested",
                              font=("Segoe UI Variable", 9), bg=WARN_BG,
                              fg=WARN_FG, activebackground=WARN_HOVER,
                              relief="flat", padx=10, pady=4,
                              command=_request_via_trello
                              ).pack(side="left", padx=(8, 0))
                tk.Button(br, text="Import", font=("Segoe UI Variable", 9, "bold"),
                          bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                          relief="flat", padx=12, pady=4, command=_ok).pack(side="right")
                dlg.wait_window()
                if not _proceed[0]:
                    return
                try:
                    zips = sorted(
                        [f for f in os.listdir(DOWNLOADS)
                         if DOCUSKETCH_RE.match(f)
                         and os.path.isfile(os.path.join(DOWNLOADS, f))],
                        key=lambda f: os.path.getmtime(os.path.join(DOWNLOADS, f)),
                        reverse=True)
                except OSError:
                    messagebox.showerror("Error", "Could not read Downloads folder.")
                    return
                if not zips:
                    messagebox.showerror("Not Found",
                        "No Docusketch zip found in Downloads.\n\n"
                        "Expected: Tour_*_Order_*_all_sketches*.zip")
                    return
                chosen = zips[0]
                if len(zips) > 1:
                    dlg = tk.Toplevel(self)
                    dlg.title("Select Docusketch Zip")
                    dlg.resizable(False, False)
                    dlg.grab_set()
                    f = tk.Frame(dlg, bg=BG, padx=16, pady=14)
                    f.pack()
                    tk.Label(f, text="Multiple zips found — pick one:",
                             font=("Segoe UI Variable", 10, "bold"), bg=BG).pack(anchor="w", pady=(0,8))
                    pick_var = tk.StringVar(value=zips[0])
                    for z in zips[:6]:
                        tk.Radiobutton(f, text=z, variable=pick_var, value=z,
                                       font=("Segoe UI Variable", 8), bg=BG,
                                       activebackground=BG).pack(anchor="w", pady=2)
                    result = [None]
                    def _pick():
                        result[0] = pick_var.get()
                        dlg.destroy()
                    tk.Button(f, text="Import", font=("Segoe UI Variable", 10, "bold"),
                              bg=GREEN, fg=WHITE, relief="flat", padx=12, pady=4,
                              command=_pick).pack(pady=(12, 0), fill="x")
                    dlg.wait_window()
                    if not result[0]:
                        return
                    chosen = result[0]
                zip_path = os.path.join(DOWNLOADS, chosen)
                ems = os.path.join(cp, "EMS")
                base = ems if os.path.isdir(ems) else cp
                docs = find_docs_dir(base) or os.path.join(base, "DOCS")
                os.makedirs(docs, exist_ok=True)
                ds_folder = os.path.join(docs, "Docusketch")
                os.makedirs(ds_folder, exist_ok=True)
                try:
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        z.extractall(ds_folder)
                except Exception as ex:
                    messagebox.showerror("Extract Error", str(ex))
                    return
                # Recycle the source zip — per user direction, every
                # successful import from Downloads sends the source to
                # the Recycle Bin to keep Downloads from accumulating
                # already-imported files. Recoverable in case of a
                # misclick.
                _trash_imported_zips(zip_path)
                var.set(True)
                lbl.config(fg=TEXT_MUTED, font=("Segoe UI Variable", 8, "overstrike"))
                if all(v.get() for v in all_v) and not cr[0]:
                    cr[0] = True
                    bl.config(text=" OK ", bg=GREEN)
                    ca.config(highlightbackground=GREEN)
                    resolved[0] += 1
                    _update_status()
                if on_success:
                    try:
                        on_success()
                    except Exception:
                        pass
                # Auto-clear any pending docusketch-request reminder for
                # this client.
                _ds_card_id = ""
                try:
                    import docusketch_requests as dr
                    if client_name:
                        hit = dr.find_card_for_client(client_name)
                        if hit is not None:
                            _ds_card_id = hit.get("card_id") or ""
                            dr.resolve(_ds_card_id)
                except Exception:
                    pass
                # Auto-tick the matching Trello checklist item now that
                # the sketch is on disk. Prefer the pinned card_id from
                # persistence when available — docusketch_requests fuzz-
                # matches by name, which can pick the wrong job when
                # two clients share a surname.
                try:
                    import persistence as _per
                    _pin_id = (_per.get_trello_card_id(client_name)
                                or "") if client_name else ""
                    _tick_card = _pin_id or _ds_card_id
                    if _tick_card:
                        import trello_autotick as _at
                        _at.autotick(
                            _tick_card,
                            events=("docusketch_imported",),
                            client=client_name)
                except Exception:
                    pass
                messagebox.showinfo("Docusketch Imported", f"Extracted to:\n{ds_folder}")
            return _do

        def _make_workcenter_action(cp, var, lbl, all_v, bl, ca, cr,
                                     is_photo, item_txt, client_name,
                                     on_success=None):
            """Mirror the Docusketch import flow for Workcenter exports.
            User clicks the WC button → we pop the WC URL in a browser
            AND show a wait-for-zip dialog; on confirm we grab the
            freshest matching zip from Downloads (documents* for forms,
            attachments* for photos) and extract into the right place.
            Photo zips usually have stage subfolders (Initial /
            Mitigation / etc.) — extractall preserves that structure
            so each stage lands in its own subfolder under PICS instead
            of being flattened together."""
            zip_re = WC_ATTACHMENTS_RE if is_photo else WC_DOCUMENTS_RE
            label  = "attachments" if is_photo else "documents"
            kind   = "photos" if is_photo else "forms"
            import wc_zip_import as _wcz
            def _do():
                _pr = _wcz.prompt_for_wc_zip(self,
                                              workcenter_url=WORKCENTER_URL,
                                              label=label, kind=kind)
                if not _pr:
                    return
                if isinstance(_pr, list):
                    # User hand-picked file(s) from Downloads.
                    chosen_label, chosen_paths = ("picked files", _pr)
                else:
                    groups = _wcz.find_wc_zips(DOWNLOADS, zip_re)
                    if not groups:
                        messagebox.showerror("Not Found",
                            f"No Workcenter {kind} zip found in Downloads.\n\n"
                            f"Expected: {label}*.zip\n\n"
                            "Tip: use “📁 Pick a file…” to choose any file "
                            "manually.")
                        return
                    picked = _wcz.pick_zip_group(self, groups, label=label)
                    if picked is None:
                        return
                    chosen_label, chosen_paths = picked
                # Pick the extraction target: photos go into the
                # highest-priority PICS variant under the job (so
                # multi-stage zips land in the same tree audits walk),
                # forms go into EMS/DOCS where check_forms looks.
                if is_photo:
                    # Multi-unit jobs need a per-unit destination —
                    # the WC zip filename doesn't carry unit info, so
                    # ask the user which unit these photos belong to.
                    # Cancellable; cancel aborts the import entirely.
                    chosen_unit_path = None
                    try:
                        from multi_unit_gui import list_unit_subfolders
                        unit_list = list_unit_subfolders(cp)
                    except Exception:
                        unit_list = []
                    if unit_list:
                        chosen_unit_path = _ask_unit_for_import(
                            self, unit_list, kind=kind,
                            client_name=client_name)
                        if chosen_unit_path is None:
                            return
                    if chosen_unit_path:
                        # Use the picked unit's EMS/PICS directly.
                        target = os.path.join(
                            chosen_unit_path, "EMS", "PICS")
                        os.makedirs(target, exist_ok=True)
                    else:
                        pics_opts = _resolve_all_pics_folders(cp)
                        if not pics_opts:
                            target = os.path.join(cp, "EMS", "PICS")
                            os.makedirs(target, exist_ok=True)
                        else:
                            # _resolve_all_pics_folders → [(label, path,
                            # count), ...] in priority order.
                            target = pics_opts[0][1]
                    # Stage routing: drop into PICS/<Stage>/ when the
                    # audit row is stage-tagged ("Initial pics", "Demo
                    # pics", "Mold Prep pics", …) so audits match the
                    # stage keyword inside the folder name. Skipped for
                    # generic / unstaged photo rows — those land at the
                    # PICS root, same as before.
                    stage = _stage_folder_for_item(item_txt)
                    if stage:
                        target = os.path.join(target, stage)
                        os.makedirs(target, exist_ok=True)
                    # Sticky-home override: when ≥2 image basenames in
                    # the WC zip already exist somewhere under PICS,
                    # route the whole batch to that OD subfolder. Keeps
                    # related photos together instead of seeding a new
                    # stage subfolder. Walks from the PICS root so the
                    # heuristic sees every existing subfolder regardless
                    # of stage.
                    try:
                        _pics_root = (
                            os.path.dirname(target)
                            if stage else target)
                        _home = _wcz.find_sticky_home(
                            chosen_paths, _pics_root)
                        if _home:
                            target = _home
                            os.makedirs(target, exist_ok=True)
                    except Exception:
                        pass
                else:
                    ems = os.path.join(cp, "EMS")
                    base = ems if os.path.isdir(ems) else cp
                    docs = find_docs_dir(base) or os.path.join(base, "DOCS")
                    os.makedirs(docs, exist_ok=True)
                    target = docs
                try:
                    _wcz.place_import_paths(chosen_paths, target)
                except Exception as ex:
                    messagebox.showerror("Extract Error", str(ex))
                    return
                # Photos only: convert HEIC → JPEG, then sort into
                # per-room subfolders (Bed 1, Bath 2, Garage…) when the
                # filenames carry room labels. Both no-op safely when
                # there's nothing to do.
                if is_photo:
                    try:
                        from wc_zip_import import (convert_heic_in_dir,
                                                    organize_by_room)
                        convert_heic_in_dir(target)
                        organize_by_room(target)
                    except Exception:
                        pass
                # Recycle every part of the WC zip — multi-part archives
                # (documents-part-1-of-2.zip + ...-of-2.zip) all get
                # trashed since they were all extracted together.
                _trash_imported_zips(chosen_paths)
                var.set(True)
                lbl.config(fg=TEXT_MUTED,
                           font=("Segoe UI Variable", 8, "overstrike"))
                # Persist resolution so today's audit + tomorrow's
                # carry-forward pre-check stay aligned.
                try:
                    persistence.set_resolved(self.run_date, client_name,
                                              persist_key(item_txt), True)
                except Exception:
                    pass
                if all(v.get() for v in all_v) and not cr[0]:
                    cr[0] = True
                    bl.config(text=" OK ", bg=GREEN)
                    ca.config(highlightbackground=GREEN)
                    resolved[0] += 1
                    _update_status()
                if on_success:
                    try:
                        on_success()
                    except Exception:
                        pass
                # Auto-tick Trello checklist for the kind we just
                # imported. is_photo is set on the closure; photos →
                # "Initial photos / photo report" line, docs → "Initial
                # paperwork" line. Initial-stage photos only — non-
                # initial rows (Demo, Mold Prep, Final) don't have a
                # mapped checklist item.
                try:
                    import persistence as _per
                    _card_id = (_per.get_trello_card_id(client_name)
                                or "") if client_name else ""
                    if _card_id:
                        _events: list[str] = []
                        if is_photo:
                            # Only tick the Initial line when the audit
                            # row was the Initial-pics row. item_txt
                            # tells us which stage row triggered the
                            # import — bail otherwise so we don't tick
                            # "Initial photos" for a Demo upload.
                            if "initial" in (item_txt or "").lower():
                                _events.append("sp_photos_initial")
                        else:
                            _events.append("wc_docs_imported")
                        if _events:
                            import trello_autotick as _at
                            _at.autotick(_card_id,
                                         events=tuple(_events),
                                         client=client_name)
                except Exception:
                    pass
                msg = f"Extracted {kind} to:\n{target}"
                if len(chosen_paths) > 1:
                    msg = (f"Extracted {len(chosen_paths)} parts "
                           f"({chosen_label}) to:\n{target}")
                messagebox.showinfo("Workcenter Imported", msg)
            return _do

        def _make_docusign_action(cp, var, lbl, all_v, bl, ca, cr,
                                   item_txt, client_name, on_success=None):
            """Mirror the WC-forms import for DocuSign Final-Paperwork zips.
            Looks in Downloads for `<Client>_Final_Paperwork.zip`, extracts
            into EMS/DOCS, and crosses off every audit row whose missing-
            form label the zip just resolved (not just the row clicked).

            Falls back to the most-recent DocuSign zip in Downloads when
            the client surname doesn't match — same "newest wins" behavior
            the WC import uses for ambiguous downloads.

            Pre-import dialog branches: the user can either ✍ Request the
            DocuSign via Trello (posts a comment + records a Hygiene
            pending entry, parallels the Docusketch flow), or proceed to
            import a signed packet they already have in Downloads."""
            def _do():
                # ── Pre-import branch dialog ──────────────────────────
                dlg = tk.Toplevel(self)
                dlg.title("DocuSign")
                dlg.resizable(False, False)
                dlg.grab_set()
                wf = tk.Frame(dlg, bg=BG, padx=20, pady=16)
                wf.pack()
                tk.Label(wf,
                         text=(f"DocuSign Final Paperwork for "
                               f"{client_name or 'this client'}"),
                         font=("Segoe UI Variable", 10, "bold"),
                         bg=BG).pack(anchor="w")
                tk.Label(wf,
                         text=("Send the paperwork via Trello (Hygiene "
                               "will nag daily until it's signed), or "
                               "import a signed packet from Downloads."),
                         font=("Segoe UI Variable", 9),
                         bg=BG, fg=TEXT_GRAY,
                         wraplength=420, justify="left"
                         ).pack(anchor="w", pady=(4, 12))

                def _request_via_trello():
                    try:
                        from docusketch_requests import find_card_for_client
                        import docusign_requests as dsr
                        hit = find_card_for_client(client_name)
                    except Exception as ex:
                        messagebox.showerror(
                            "Lookup failed",
                            f"Couldn't search Trello: {ex}",
                            parent=dlg)
                        return
                    if hit is None:
                        messagebox.showwarning(
                            "No card found",
                            f"Couldn't find a Trello card for "
                            f"'{client_name}'. Open the card manually "
                            f"and request DocuSign via Trello.",
                            parent=dlg)
                        return
                    entry = dsr.request(hit["card_id"],
                                          client_name=client_name)
                    if entry is None:
                        messagebox.showerror(
                            "Couldn't record",
                            "Trello request failed. Check ems.log.",
                            parent=dlg)
                        return
                    email = entry.get("email") or ""
                    if entry.get("state") == "pending_signature":
                        msg = (f"Posted to {entry['card_name']}.\n\n"
                               f"DocuSign paperwork sent to {email} — "
                               f"awaiting signature. The Hygiene "
                               f"panel's '✍ Docusign pending' "
                               f"section will nag daily until it's "
                               f"signed.")
                    else:
                        msg = (f"Posted to {entry['card_name']}.\n\n"
                               f"No email on file — pinged "
                               f"{dsr.KIMBERLY_HANDLE} on the Trello "
                               f"card to get one. Hygiene will show "
                               f"the row with a '✉ Got email' "
                               f"button.")
                    if not entry.get("comment_posted", True):
                        msg = ("Recorded locally, but the Trello "
                               "comment failed to post. Open the card "
                               "and post manually.")
                    messagebox.showinfo("DocuSign requested",
                                          msg, parent=dlg)
                    dlg.destroy()

                _proceed = [False]
                def _ok():
                    _proceed[0] = True
                    dlg.destroy()

                br = tk.Frame(wf, bg=BG)
                br.pack(fill="x")
                tk.Button(br, text="Cancel",
                          font=("Segoe UI Variable", 9), bg=SURFACE_2,
                          fg=TEXT_DARK, relief="flat", padx=12, pady=4,
                          command=dlg.destroy).pack(side="left")
                if client_name:
                    tk.Button(br, text="✍ Request via Trello",
                              font=("Segoe UI Variable", 9),
                              bg=WARN_BG, fg=WARN_FG,
                              activebackground=WARN_HOVER,
                              relief="flat", padx=10, pady=4,
                              command=_request_via_trello
                              ).pack(side="left", padx=(8, 0))
                tk.Button(br, text="Import",
                          font=("Segoe UI Variable", 9, "bold"),
                          bg=GREEN, fg=WHITE,
                          activebackground=GREEN_DARK,
                          relief="flat", padx=12, pady=4,
                          command=_ok).pack(side="right")
                dlg.wait_window()
                if not _proceed[0]:
                    return

                try:
                    import docusign_import as dsi
                except ImportError as ex:
                    messagebox.showerror(
                        "DocuSign import unavailable", str(ex))
                    return
                zips = dsi.find_docusign_zips(DOWNLOADS,
                                               client_hint=client_name)
                if not zips:
                    messagebox.showerror(
                        "Not Found",
                        "No DocuSign Final-Paperwork zip found in "
                        "Downloads.\n\n"
                        "Expected: <Client>_Final_Paperwork.zip")
                    return
                chosen = zips[0]
                if len(zips) > 1:
                    pick_dlg = tk.Toplevel(self)
                    pick_dlg.title("Select DocuSign zip")
                    pick_dlg.resizable(False, False)
                    pick_dlg.grab_set()
                    f = tk.Frame(pick_dlg, bg=BG, padx=16, pady=14)
                    f.pack()
                    tk.Label(f,
                             text="Multiple DocuSign zips found — pick one:",
                             font=("Segoe UI Variable", 10, "bold"), bg=BG
                             ).pack(anchor="w", pady=(0, 8))
                    pick_var = tk.IntVar(value=0)
                    for idx, fn in enumerate(zips[:6]):
                        tk.Radiobutton(f, text=fn, variable=pick_var,
                                       value=idx,
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
                        return
                    chosen = zips[picked[0]]
                zip_path = os.path.join(DOWNLOADS, chosen)
                ems  = os.path.join(cp, "EMS")
                base = ems if os.path.isdir(ems) else cp
                docs = find_docs_dir(base) or os.path.join(base, "DOCS")
                try:
                    landed = dsi.import_zip(zip_path, docs)
                except Exception as ex:
                    messagebox.showerror("Extract Error", str(ex))
                    return
                # Recycle the source DocuSign packet — same cleanup
                # rule as the other importers.
                _trash_imported_zips(zip_path)
                # Persist resolution + cross off the row that was clicked.
                var.set(True)
                lbl.config(fg=TEXT_MUTED,
                           font=("Segoe UI Variable", 8, "overstrike"))
                try:
                    persistence.set_resolved(self.run_date, client_name,
                                              persist_key(item_txt), True)
                except Exception:
                    pass
                if all(v.get() for v in all_v) and not cr[0]:
                    cr[0] = True
                    bl.config(text=" OK ", bg=GREEN)
                    ca.config(highlightbackground=GREEN)
                    resolved[0] += 1
                    _update_status()
                # Sibling cross-offs (e.g. ATP+CIF+CoS all signed in one
                # packet) happen automatically via on_success →
                # _refresh_card_after_action, which re-walks EMS/DOCS
                # and unflags any row whose missing-form check now passes.
                if on_success:
                    try:
                        on_success()
                    except Exception:
                        pass
                # Auto-tick the matching Trello checklist item — same
                # event the WC docs import fires so the card's
                # paperwork line crosses off without manual click.
                try:
                    import persistence as _per
                    _cid = (_per.get_trello_card_id(client_name)
                             or "") if client_name else ""
                    if _cid:
                        import trello_autotick as _at
                        _at.autotick(_cid,
                                      events=("wc_docs_imported",),
                                      client=client_name)
                except Exception:
                    pass
                # Auto-clear any pending Docusign-request reminder —
                # the signed packet is on disk so the Hygiene nag is no
                # longer warranted. Mirrors the docusketch import flow.
                try:
                    import docusign_requests as _dsr
                    if client_name:
                        from docusketch_requests import find_card_for_client
                        _hit = find_card_for_client(client_name)
                        if _hit is not None:
                            _dsr.resolve(_hit["card_id"])
                except Exception:
                    pass
                summary = dsi.summarize_landed(landed)
                messagebox.showinfo(
                    "DocuSign Imported",
                    f"Extracted to:\n{docs}\n\nForms: {summary}")
            return _do

        def _make_smart_import_action(cp, var, lbl, all_v, bl, ca, cr,
                                        *, item_txt, client_name,
                                        is_photo, is_ds_signable,
                                        show_wc, on_success=None):
            """Unified row-import: scan Downloads for any zip that's
            relevant to this row's context, route to the matching
            importer. Single-match auto-fires; multi-match shows a
            small picker. Replaces the earlier separate 📥 WC docs /
            📥 WC photos / 📝 DS buttons per user request — they wanted
            one button that "scans and pulls in whatever we
            downloaded regardless."
            """
            def _do():
                # Build the candidate list: (display_label, lazy_action).
                candidates = []

                if show_wc:
                    try:
                        from wc_zip_import import find_wc_zips as _f
                    except Exception:
                        _f = None
                    if _f is not None and is_photo:
                        try:
                            groups = _f(DOWNLOADS, WC_ATTACHMENTS_RE)
                        except Exception:
                            groups = []
                        if groups:
                            candidates.append((
                                f"📷 Workcenter photos "
                                f"({len(groups)} in Downloads)",
                                _make_workcenter_action(
                                    cp, var, lbl, all_v, bl, ca, cr,
                                    is_photo=True, item_txt=item_txt,
                                    client_name=client_name,
                                    on_success=on_success)))
                    if _f is not None and not is_photo:
                        try:
                            groups = _f(DOWNLOADS, WC_DOCUMENTS_RE)
                        except Exception:
                            groups = []
                        if groups:
                            candidates.append((
                                f"📄 Workcenter docs "
                                f"({len(groups)} in Downloads)",
                                _make_workcenter_action(
                                    cp, var, lbl, all_v, bl, ca, cr,
                                    is_photo=False, item_txt=item_txt,
                                    client_name=client_name,
                                    on_success=on_success)))

                if is_ds_signable:
                    try:
                        import docusign_import as _dsi
                        ds_zips = _dsi.find_docusign_zips(
                            DOWNLOADS, client_hint=client_name)
                    except Exception:
                        ds_zips = []
                    # Always include DS as a candidate — when there's
                    # a signed packet in Downloads we surface the
                    # import; when there ISN'T, we still need the
                    # "✍ Send DocuSign via Trello" path so the user
                    # can request signatures from inside the audit row.
                    # Both routes call _make_docusign_action, which
                    # opens the branch dialog with Request / Import.
                    if ds_zips:
                        ds_label = (f"📝 DocuSign signed packet "
                                    f"({len(ds_zips)} in Downloads)")
                    else:
                        ds_label = "✍ Send DocuSign via Trello"
                    candidates.append((
                        ds_label,
                        _make_docusign_action(
                            cp, var, lbl, all_v, bl, ca, cr,
                            item_txt=item_txt,
                            client_name=client_name,
                            on_success=on_success)))

                if not candidates:
                    looked_for = []
                    if show_wc and is_photo:
                        looked_for.append(
                            "Workcenter attachments*.zip")
                    elif show_wc:
                        looked_for.append("Workcenter documents*.zip")
                    if is_ds_signable:
                        looked_for.append(
                            "<Client>_Final_Paperwork.zip "
                            "(DocuSign packet)")
                    looked_msg = ("\n  • ".join(looked_for)
                                  if looked_for else "(nothing applicable)")
                    messagebox.showinfo(
                        "Nothing to import",
                        f"No importable zip found in Downloads.\n\n"
                        f"Looked for:\n  • {looked_msg}",
                        parent=self)
                    return

                if len(candidates) == 1:
                    candidates[0][1]()
                    return

                # Multiple types in Downloads — small picker dialog so
                # the user disambiguates instead of us guessing.
                dlg = tk.Toplevel(self)
                dlg.title("Import from Downloads")
                dlg.resizable(False, False)
                dlg.grab_set()
                wf = tk.Frame(dlg, bg=BG, padx=20, pady=14)
                wf.pack(fill="both", expand=True)
                tk.Label(wf,
                          text="Multiple importable zips found in "
                               "Downloads — pick one:",
                          font=("Segoe UI Variable", 10, "bold"),
                          bg=BG, fg=TEXT_DARK
                          ).pack(anchor="w", pady=(0, 10))
                for label, action in candidates:
                    def _fire(a=action):
                        dlg.destroy()
                        a()
                    tk.Button(wf, text=label,
                               font=("Segoe UI Variable", 9),
                               bg=SURFACE_2, fg=TEXT_DARK,
                               relief="flat", padx=16, pady=8,
                               anchor="w", cursor="hand2",
                               command=_fire
                               ).pack(fill="x", pady=3)
                tk.Button(wf, text="Cancel",
                           font=("Segoe UI Variable", 9), bg=SURFACE_2,
                           fg=TEXT_DARK, relief="flat", padx=12, pady=4,
                           command=dlg.destroy
                           ).pack(pady=(12, 0))
            return _do

        _update_status()

        # Column header over the item checkboxes
        col_hdr = tk.Frame(self._inner, bg=BG)
        col_hdr.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(col_hdr, text="Next Item", font=("Segoe UI Variable", 7, "bold"),
                 bg=BG, fg=TEXT_GRAY).pack(side="left", padx=(40, 0))
        tk.Label(col_hdr, text="Completed", font=("Segoe UI Variable", 7, "bold"),
                 bg=BG, fg=TEXT_GRAY).pack(side="right", padx=(0, 14))

        # Map client → section so we can group cards under section
        # banners. Lookup is case/whitespace-folded to match the same
        # normalization the merge step uses, so a result whose name
        # came back slightly different from what was parsed still
        # resolves. Anything not in self.jobs (rare — fallback paths
        # like single-job audits or stale cache) lands under "Other".
        def _norm_key(s):
            return " ".join((s or "").lower().split())
        client_section = {}
        for j in (self.jobs or []):
            client_section[_norm_key(j.get("client"))] = j.get("section")

        # Friendly labels + accent colors for each section banner.
        # Work = green (active work), Monitor = blue (watch list).
        _SECTION_META = {
            "work":    ("Work to Be Performed",  "#1F6B3F", "#E8F5EE"),
            "monitor": ("Monitor",                "#1F4E8A", "#E6EFFA"),
            "other":   ("Other",                  TEXT_DARK,  "#EFEFEF"),
        }

        def _render_section_banner(section_key, count):
            label, fg, bg_tint = _SECTION_META.get(
                section_key, _SECTION_META["other"])
            bar = tk.Frame(self._inner, bg=bg_tint,
                            highlightbackground=fg,
                            highlightthickness=0)
            bar.pack(fill="x", padx=6, pady=(10, 2))
            # Left accent stripe makes the section transition pop in
            # peripheral vision while scrolling.
            tk.Frame(bar, bg=fg, width=4).pack(side="left", fill="y")
            tk.Label(bar, text=f"  {label}",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=bg_tint, fg=fg, padx=8, pady=4
                     ).pack(side="left")
            tk.Label(bar, text=f"{count} job{'s' if count != 1 else ''}",
                     font=("Segoe UI Variable", 8),
                     bg=bg_tint, fg=fg, padx=8, pady=4
                     ).pack(side="right")

        # Pre-count results per section so the banner can show the
        # group total — cleaner than counting twice or tracking
        # incrementally.
        section_counts = {}
        for r in results:
            sec = client_section.get(_norm_key(r.get("client"))) or "other"
            section_counts[sec] = section_counts.get(sec, 0) + 1
        # Streaming kicks off with results=[] so the per-results count
        # would be 0 — seed from the run-doc's own job list (which
        # already has section info) so banners show the final count
        # the moment the first card of each section lands.
        if streaming and not section_counts:
            for j in (self.jobs or []):
                sec = j.get("section") or "other"
                section_counts[sec] = section_counts.get(sec, 0) + 1

        # Mutable wrapper so the closure below can carry section state
        # across calls in streaming mode (each card may transition
        # sections; we render the banner once per transition).
        prev_section = [None]

        def _render_one_card(r, *, before=None):
            """Render one audit-result card. When `before` is a sibling
            widget, the card is packed immediately above it instead of
            appended to the end — used by `_refresh_single_card` to
            preserve the row's existing scroll position after a
            single-card re-audit.

            Skips the streaming bookkeeping path when `before` is set,
            since that path assumes new cards arriving in feed order;
            re-rendering a single existing card shouldn't touch the
            totals or banner state.
            """
            in_place_refresh = before is not None
            if not in_place_refresh:
                current_section = (
                    client_section.get(_norm_key(r.get("client"))) or "other")
                if current_section != prev_section[0]:
                    _render_section_banner(current_section,
                                            section_counts[current_section])
                    prev_section[0] = current_section
                # Streaming bookkeeping: bump totals as cards arrive so the
                # status line reflects what's on screen rather than the
                # initial expected_total seed.
                if streaming:
                    if total_box[0] < len(self._streaming_results) + 1:
                        # Shouldn't happen normally — defensive against the
                        # caller stashing more results than expected_total.
                        total_box[0] = len(self._streaming_results) + 1
                    if r.get("flagged"):
                        flagged_box[0] += 1
                    self._streaming_results.append(r)
            # Card is one Frame with internal padding (no inner `row`
            # wrapper) — fewer widgets per audit row = less repaint cost
            # on scroll. The 1-pixel highlight border is the only visual
            # chrome; everything else is laid out directly inside.
            card = tk.Frame(self._inner, bg=WHITE, padx=10, pady=6,
                            highlightbackground=BORDER, highlightthickness=1)
            _pack_kwargs = {"fill": "x", "padx": 6, "pady": 2}
            if before is not None:
                _pack_kwargs["before"] = before
            card.pack(**_pack_kwargs)
            # Track by client so `_refresh_single_card` can find this
            # card later. Last-write-wins on duplicates (rare — same
            # client in two sections would already be ambiguous).
            try:
                _cli = (r.get("client") or "").strip()
                if _cli:
                    self._card_by_client[_cli] = card
            except Exception:
                pass

            # Right-click context menu for clearing per-client memory
            self._attach_card_context_menu(card, r)

            badge_bg  = FLAG_RED if r["flagged"] else GREEN
            badge_txt = "FLAG" if r["flagged"] else " OK "
            badge_lbl = tk.Label(card, text=badge_txt, font=("Segoe UI Variable", 8, "bold"),
                                 bg=badge_bg, fg=WHITE, padx=4)
            badge_lbl.pack(side="left")
            attach_tooltip(badge_lbl,
                            "Audit found issue(s) — see checklist below"
                            if r["flagged"]
                            else "Folder is clean — no audit issues")

            # Repeat-offender badge: this folder has been flagged in many
            # past audits without resolving. Color ramps from orange (5+)
            # to red (20+) so chronic backlog drag is visually obvious.
            rep_count = audit_count_idx.get(
                ((r.get("folder") or "").strip(),
                 (r.get("unit") or "").strip().lower()), 0)
            if r.get("flagged") and rep_count >= 5:
                rep_bg = "#7B1818" if rep_count >= 20 else (
                          "#E67E22" if rep_count >= 10 else "#C39A37")
                rep_lbl = tk.Label(
                    card, text=f"↻ {rep_count}x",
                    font=("Segoe UI Variable", 7, "bold"),
                    bg=rep_bg, fg=WHITE, padx=3)
                rep_lbl.pack(side="left", padx=(2, 0))
                attach_tooltip(rep_lbl,
                                f"Flagged in {rep_count} past audits "
                                "without resolving — chronic backlog")

            # Saved-memory pin indicator (folder override / commercial / note)
            client_name = r["client"]
            render_memory_pin(card, client_name, path=r.get("path"), bg=WHITE)

            # Sync-state warning. ONLY checked on flagged rows so we
            # don't pay the per-row stat cost when the audit is clean.
            # Surfaces cloud-only OneDrive placeholders that the audit
            # can't actually see — distinguishes "real missing files"
            # from "waiting on SP sync". Cached on the row dict by
            # `_check_sync_state` so a re-render of the same card
            # doesn't re-walk the tree.
            if r.get("flagged") and r.get("path"):
                try:
                    sync_count = self._check_sync_state(r)
                except Exception:
                    sync_count = 0
                if sync_count > 0:
                    sync_lbl = tk.Label(
                        card,
                        text=f" ☁ {sync_count} cloud-only ",
                        font=("Segoe UI Variable", 7, "bold"),
                        bg=WARN_BG, fg=WARN_FG,
                        padx=4)
                    sync_lbl.pack(side="left", padx=(2, 0))
                    samples = r.get("_sync_samples") or []
                    tip = ("Files visible in Explorer but content "
                           "not on disk yet — OneDrive sync still "
                           "pulling. The audit can't read these so "
                           "flags may be false-positives until sync "
                           "completes.")
                    if samples:
                        tip += "\n\nExamples:\n  " + "\n  ".join(
                            samples[:6])
                        if len(samples) > 6:
                            tip += f"\n  …+{len(samples)-6} more"
                    attach_tooltip(sync_lbl, tip)
                    # 🔄 Force-sync button: opens each cloud-only file
                    # with a 1-byte read to make OneDrive pull content.
                    # Slow (network round-trip per file) so we thread it.
                    force_btn = tk.Button(
                        card,
                        text="🔄",
                        font=("Segoe UI Variable", 8),
                        bg=WARN_BG, fg=WARN_FG,
                        bd=0, padx=4, cursor="hand2",
                        activebackground=WARN_HOVER)
                    force_btn.pack(side="left", padx=(0, 2))
                    attach_tooltip(force_btn,
                                   "Force OneDrive to download every "
                                   "cloud-only file under this job. "
                                   "Slow — runs in the background. "
                                   "Re-checks the audit when done.")
                    force_btn.configure(
                        command=lambda rr=r, btn=force_btn:
                            self._force_sync_row(rr, btn))

            detail = tk.Frame(card, bg=WHITE)
            detail.pack(side="left", fill="x", expand=True)

            name_row = tk.Frame(detail, bg=WHITE)
            name_row.pack(fill="x")

            name_txt = f"  {r['client']}"
            # Folder-not-found state is signalled by the gray text color
            # (fg=TEXT_MUTED) below — the old "  — folder not found" suffix
            # was a second cue for the same fact, just visual clutter on
            # the rows where it mattered most. Right-click → Find Folder
            # is still how the user resolves it.
            if r["found"] and r.get("folder", "").lower() != r["client"].lower():
                name_txt += f"  ({r['folder']})"
            # Name label expands to fill, replacing the old empty spacer Frame
            # that used to push action buttons flush-right.
            tk.Label(name_row, text=name_txt, font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_MUTED if not r["found"] else TEXT_DARK,
                     anchor="w").pack(side="left", fill="x", expand=True)

            # New-loss pill — visible status tag, NOT a checklist item.
            if r.get("new_loss"):
                _nl_lbl = tk.Label(name_row, text=" NEW LOSS ",
                                    font=("Segoe UI Variable", 7, "bold"),
                                    bg=WARN_BG, fg=WARN_FG,
                                    padx=4, pady=1)
                _nl_lbl.pack(side="left", padx=(6, 0))
                attach_tooltip(_nl_lbl,
                                "New job — first time the audit has "
                                "seen this client")

            # Multi-unit property pill — when this client looks like a
            # unit of a known multi-unit property (Avila Apartments
            # 1416, etc.), show the property name as a sibling-aware
            # chip. Streams cleanly because each card self-identifies;
            # no in-flight reorder needed.
            try:
                import ems_db as _db
                prop_name, _unit = _db.detect_property_and_unit(
                    r.get("client") or "")
            except Exception:
                prop_name = None
            if prop_name:
                _prop_lbl = tk.Label(
                    name_row, text=f" 🏢 {prop_name} ",
                    font=("Segoe UI Variable", 7, "bold"),
                    bg=LINK_BG, fg=LINK_FG,
                    padx=4, pady=1)
                _prop_lbl.pack(side="left", padx=(6, 0))
                attach_tooltip(_prop_lbl,
                                f"Part of {prop_name} (multi-unit property)")

            # Time-slot pill — when the run-doc dispatch line specified
            # an appointment window (e.g. "9-11", "1-3pm", "@12pm"),
            # show it next to the row so the user can see when this
            # job is going without re-opening the doc. Surfaced for
            # Monitor rows AND for Work-section new-losses, since
            # those are the lines that typically carry a slot.
            time_slot = r.get("time_slot")
            if time_slot:
                ts_text = (time_slot if time_slot.startswith("@")
                           else f"🕒 {time_slot}")
                _ts_lbl = tk.Label(name_row, text=f" {ts_text} ",
                                    font=("Segoe UI Variable", 7, "bold"),
                                    bg=LINK_BG, fg=LINK_FG,
                                    padx=4, pady=1)
                _ts_lbl.pack(side="left", padx=(6, 0))
                attach_tooltip(_ts_lbl,
                                f"Appointment time from the run-doc: "
                                f"{time_slot}")

            # Initialize all conditional button refs to None up front so
            # the IUQ-order reorder pass at the bottom of this block
            # can reference them whether or not their if-block fired.
            open_dir_btn = None
            _mk_btn = None
            unit_btn = None
            esc_btn = None
            flag_btn = None
            # 📌 Flag missing — same per-row button the IUQ has, scoped
            # to this audit row's client/card. Mirrors IUQ behavior so
            # the user has one consistent affordance for "I see
            # something missing — track it" across both panels. Stage
            # tag is "audit" so Hygiene attributes the gap to the
            # daily audit step (not intake or snapshot).
            try:
                _card_id_for_flag = (persistence.get_trello_card_id(
                    r.get("client") or "") or "")
            except Exception:
                _card_id_for_flag = ""
            flag_btn = link_button(
                name_row, "📌 Flag missing",
                command=lambda c=r.get("client") or "",
                                 cid=_card_id_for_flag:
                    self._open_flag_missing_for_row(c, cid),
                tooltip="Flag a missing item on this row — adds a "
                        "Trello comment and tracks it in Hygiene.",
            )
            flag_btn.pack(side="right", padx=(0, 2))
            if r["path"]:
                # 📁 OD — matches the Initial Upload row's "📁 OD"
                # button shape so the user reads the same affordance
                # across both tools (LINK_BG pill, same padding, same
                # font weight). The right-click menu still drives the
                # "change folder" workflow.
                open_dir_btn = link_button(
                    name_row, "📁 OD",
                    command=lambda p=r["path"]: os.startfile(p),
                    tooltip="Open OD folder in Explorer "
                            "(right-click row to change folder)")
                open_dir_btn.pack(side="right")

                # "Make EMS folders" — surfaces when the resolved
                # folder is missing any of EMS, EMS/DOCS, EMS/PICS.
                # New jobs often land on disk with just a raw client
                # folder; the audit can't find forms/photos until
                # those three subfolders exist. One click scaffolds
                # them and re-runs the single-card audit so the row
                # picks up the fresh state.
                _job_path = r["path"]
                _missing_subs = []
                try:
                    for _leaf, _name in (
                        ("EMS",), ("EMS/DOCS",), ("EMS/PICS",),
                    ):
                        # leaf is a tuple of path parts — split on "/"
                        _parts = _leaf[0].split("/")
                        _full = os.path.join(_job_path, *_parts)
                        if not os.path.isdir(_full):
                            _missing_subs.append(_leaf[0])
                except Exception:
                    _missing_subs = []
                if _missing_subs:
                    # 📂 Make folders — same shape as the IUQ row's
                    # button. Action is identical (scaffold EMS / DOCS
                    # / PICS); only renders when one or more of those
                    # subfolders is actually missing so it's an
                    # actionable cue, not always-on.
                    _mk_btn = link_button(
                        name_row, "📂 Make folders",
                        command=lambda c=r["client"], p=_job_path:
                            self._scaffold_ems_for_row(c, p),
                        tooltip=("Create missing EMS folder structure: "
                                 + ", ".join(_missing_subs)
                                 + ". Click to make them in this job folder."))
                    _mk_btn.pack(side="right", padx=(0, 2))

                # 🏠 Unit picker — surfaces when the resolved path has
                # unit-like subfolders (Unit 1416, UNIT #216, etc.) so
                # the user can pick which unit THIS daily-run row should
                # audit against. Common case: run-doc says "Avila
                # Apartments" with no unit and the audit lands on the
                # umbrella folder. Day-pinned via
                # persistence.set_run_day_units so tomorrow's "Avila
                # Apartments" can be different units without re-edit.
                #
                # Expanded rows (Avila — Unit 1416) get the button too:
                # their `r["path"]` is the unit folder with no children,
                # so we look at the PARENT folder for sibling units and
                # route the picker to the ORIGINAL umbrella client so
                # the user can edit / clear the multi-pin from any row.
                _unit_picker_client = r["client"]
                _unit_picker_path = r.get("path") or ""
                # Detect expanded child via the run-time lookup map first
                # (most reliable: built by _expand_multi_pinned_jobs);
                # fall back to the " — Unit " separator parse for cases
                # where the map didn't make it through (e.g. single-job
                # re-audit paths).
                _is_expanded_child = False
                _umbrella = ""
                try:
                    _expand_map = (
                        getattr(self, "_expanded_unit_lookup", None) or {})
                    if r["client"] in _expand_map:
                        _is_expanded_child = True
                except Exception:
                    pass
                if not _is_expanded_child and " — " in (r["client"] or ""):
                    _is_expanded_child = True
                if _is_expanded_child:
                    _umbrella = (r["client"] or "").split(" — ", 1)[0]
                    _unit_picker_client = _umbrella or r["client"]
                    # Look at the parent of the unit folder so siblings
                    # of the same property surface in the picker.
                    if _unit_picker_path:
                        _unit_picker_path = os.path.dirname(
                            _unit_picker_path)
                try:
                    _unit_subs = audit_logic.list_unit_subfolders(
                        _unit_picker_path)
                except Exception:
                    _unit_subs = []
                if _unit_subs:
                    # Highlight if a per-day pin is currently in effect.
                    try:
                        _day_pinned_list = persistence.get_run_day_units(
                            self.run_date, _unit_picker_client) or []
                    except Exception:
                        _day_pinned_list = []
                    _is_pinned = bool(_day_pinned_list)
                    # Synthesize an `r`-shaped dict for the picker so
                    # client/path point at the umbrella regardless of
                    # whether we got here from the umbrella or a child.
                    _picker_r = dict(r)
                    _picker_r["client"] = _unit_picker_client
                    _picker_r["path"] = _unit_picker_path
                    unit_btn = tk.Button(
                        name_row,
                        text="🏠",
                        font=("Segoe UI Variable", 9,
                              "bold" if _is_pinned else "normal"),
                        bg=LINK_BG if _is_pinned else WHITE,
                        fg=LINK_FG if _is_pinned else TEXT_GRAY,
                        relief="flat", padx=4, pady=0, cursor="hand2",
                        command=lambda rr=_picker_r, subs=_unit_subs:
                            self._open_unit_picker(rr, subs))
                    unit_btn.pack(side="right", padx=(0, 2))
                    if _is_pinned:
                        if len(_day_pinned_list) == 1:
                            pin_summary = os.path.basename(
                                _day_pinned_list[0])
                        else:
                            pin_summary = f"{len(_day_pinned_list)} units"
                        attach_tooltip(
                            unit_btn,
                            f"Day-pinned: {pin_summary}\n"
                            f"Click to change or clear.")
                    else:
                        attach_tooltip(
                            unit_btn,
                            f"{len(_unit_subs)} unit subfolders here — "
                            "click to pin one or more to this day's audit.")
                # NOTE: "Change folder…" lives in the row-wide right-click
                # menu (attached via _attach_card_context_menu). The old
                # per-button Button-3 binding was redundant and violated
                # the workflow-consistency rule — every per-row workflow
                # in one tool must mirror in every other tool with the
                # same row type, and the shared context menu is canonical.

            # Trello pin button — always present so the user can link
            # any audit row without going through Job Notes. Visual
            # state (green-fill vs outline) reflects whether at least
            # one card is currently pinned for this client.
            pinned_count = len(persistence.get_trello_card_ids(r["client"]))
            pin_btn = tk.Button(
                name_row,
                text=f"📌 {pinned_count}" if pinned_count else "📌",
                font=("Segoe UI Variable", 8, "bold" if pinned_count else "normal"),
                bg=GREEN if pinned_count else WHITE,
                fg=WHITE if pinned_count else TEXT_GRAY,
                activebackground=GREEN_DARK if pinned_count else "#E8F5EE",
                activeforeground=WHITE if pinned_count else TEXT_DARK,
                relief="flat" if pinned_count else "solid",
                bd=0 if pinned_count else 1,
                padx=4, pady=0, cursor="hand2")
            # Quick-open ↗ — opens the first pinned Trello card in the
            # browser. Only packed when at least one card is pinned, so
            # the row stays clean for unpinned clients. The pin-callback
            # below re-packs / hides this button as the pin state flips.
            def _open_pinned(_client=r["client"]):
                ids = persistence.get_trello_card_ids(_client) or []
                if not ids:
                    return
                try:
                    import webbrowser
                    webbrowser.open(f"https://trello.com/c/{ids[0]}")
                except Exception:
                    pass
            # Real Trello logo (18×18 PNG) so the popout button reads
            # as "open in Trello" at a glance. Falls back to a bold
            # white "T" on brand blue if the image fails to load
            # (e.g. trello.png missing from the deploy bundle).
            link_btn = trello_link_button(name_row, pady=0,
                                            command=_open_pinned,
                                            client=r["client"],
                                            pinned=bool(pinned_count))
            # Pack the button even when no card is pinned — right-click
            # menu still works (offers "📌 Pin Trello card…") even though
            # the left-click open is a no-op. Mirrors how the OD-folder
            # button stays visible for right-click access when no folder
            # is pinned.
            link_btn.pack(side="right", padx=(0, 2))

            def _pin_done(_ids, _btn=pin_btn, _link=link_btn,
                          _client=r["client"]):
                # Refresh the badge AND the quick-link visibility to
                # reflect new state in place — beats re-running the
                # audit just to update one label color.
                new_count = len(persistence.get_trello_card_ids(_client))
                try:
                    _btn.configure(
                        text=f"📌 {new_count}" if new_count else "📌",
                        font=("Segoe UI Variable", 8,
                              "bold" if new_count else "normal"),
                        bg=GREEN if new_count else WHITE,
                        fg=WHITE if new_count else TEXT_GRAY,
                        activebackground=GREEN_DARK if new_count else "#E8F5EE",
                        relief="flat" if new_count else "solid",
                        bd=0 if new_count else 1)
                except tk.TclError:
                    pass
                try:
                    if new_count:
                        # Re-pack BEFORE the pin button so ↗ sits
                        # immediately to the pin's left in the row.
                        _link.pack(side="right", padx=(0, 2),
                                    before=_btn)
                    else:
                        _link.pack_forget()
                except tk.TclError:
                    pass
            pin_btn.configure(
                command=lambda _client=r["client"], _cb=_pin_done:
                    open_trello_pin_dialog(self, _client, on_pinned=_cb))
            pin_btn.pack(side="right", padx=(0, 4))
            # Dynamic tooltip so the count updates as the pin state flips.
            attach_tooltip(
                pin_btn,
                lambda _c=r["client"]: (
                    f"{len(persistence.get_trello_card_ids(_c))} Trello "
                    "card(s) pinned — click to manage"
                    if persistence.get_trello_card_ids(_c)
                    else "Pin a Trello card to this client"))

            # Escalation flag — surfaces only on jobs aged ≥3 biz days,
            # opens a pre-filled Teams message per project_ems_admin_duties
            # escalation rules. Color shifts to green-check once we've
            # already escalated this run_date so the user doesn't double-
            # send. Tracked in persistence.is_escalated.
            if int(r.get("aging") or 0) >= 3 and r.get("found"):
                already = persistence.is_escalated(self.run_date,
                                                    r.get("client", ""))
                esc_btn = tk.Button(
                    name_row,
                    text="✅ 🚩" if already else "🚩",
                    font=("Segoe UI Variable", 9), bg=WHITE,
                    fg=SUCCESS_FG if already else FLAG_RED,
                    activebackground=WHITE,
                    relief="flat", padx=2, cursor="hand2")
                def _refresh_esc_btn(escalated, b=esc_btn):
                    try:
                        b.configure(text="✅ 🚩" if escalated else "🚩",
                                    fg=SUCCESS_FG if escalated else FLAG_RED)
                    except tk.TclError:
                        pass
                esc_btn.configure(
                    command=lambda rr=r, cb=_refresh_esc_btn:
                        self._open_escalation_dialog(rr, on_marked=cb))
                esc_btn.pack(side="right", padx=(0, 4))
                attach_tooltip(
                    esc_btn,
                    lambda rr=r: (
                        "Already escalated today — open dialog to re-send"
                        if persistence.is_escalated(
                            self.run_date, rr.get("client", ""))
                        else f"Escalate this aging job "
                              f"({rr.get('aging') or 0} biz days inactive)"))
            # Photo shortcut — opens this job's OneDrive PICS folder (where
            # stage subfolders like "Initial pics", "Demo pics" live). Color
            # codes whether any photos are present anywhere under PICS.
            # `pics_btn` ref is captured so the post-action refresh helper
            # below can update the count in place after a SP/WC import.
            pics_btn = None
            pics_p = r.get("pics_path")
            if pics_p:
                pics_n = r.get("pics_count", 0)
                if pics_n > 0:
                    pic_bg, pic_fg = "#E8F5EE", GREEN_DARK
                else:
                    pic_bg, pic_fg = "#FBEAE5", "#A04025"
                pics_btn = tk.Button(name_row,
                          text=f"📷 {pics_n}",
                          font=("Segoe UI Variable", 8, "bold"),
                          bg=pic_bg, fg=pic_fg,
                          activebackground=pic_bg,
                          relief="flat", padx=6, pady=1, cursor="hand2",
                          command=lambda p=pics_p: os.startfile(p))
                pics_btn.pack(side="right", padx=(0, 4))
                attach_tooltip(
                    pics_btn,
                    f"Open PICS folder — {pics_n} photo(s) counted"
                    if pics_n
                    else "PICS folder is empty — click to open")

            # SharePoint dialog trigger — three states so the user can
            # always reopen it from the row, not just when there's new
            # work to do:
            #   • amber 📥 SP +N new   — photos waiting to be copied
            #   • muted 📁 SP          — matches exist, all already in OD
            #   • faint 📁 SP          — no matches yet (dialog still
            #                            opens so the user can pin a
            #                            folder manually)
            # Forward-bound to the post-action refresh helper via a list
            # cell because the helper itself is defined further down in
            # this loop body. When the SP dialog closes after the user
            # has copied / marked / rejected anything, we hide the pill
            # and re-run the per-card refresh so flagged photo rows
            # cross off without forcing a full audit re-run.
            sp_btn = None
            refresh_after_action_cell = [None]
            sp_new = r.get("sharepoint_new", 0)
            sp_match_count = len(r.get("sharepoint_matches") or [])
            # Shape stays consistent with IUQ (factory buttons, same
            # padding) but the kind switches by state — amber/warn
            # tones for "new photos waiting" so it pops against the
            # uniform link-blue siblings, link-blue for "matches but
            # nothing new", muted for "no matches yet". Both modes
            # honor the dark/light palette via theme tokens.
            if sp_new > 0:
                sp_btn_text = f"📥 SP +{sp_new} new"
                sp_btn = warn_button(
                    name_row, sp_btn_text,
                    command=lambda rr=r,
                                    cell=refresh_after_action_cell:
                        self._open_sharepoint_download_dialog(
                            rr, on_close_changed=cell[0]))
            elif sp_match_count > 0:
                sp_btn_text = f"📁 SP ({sp_match_count})"
                sp_btn = link_button(
                    name_row, sp_btn_text,
                    command=lambda rr=r,
                                    cell=refresh_after_action_cell:
                        self._open_sharepoint_download_dialog(
                            rr, on_close_changed=cell[0]))
            else:
                sp_btn_text = "📁 SP"
                sp_btn = secondary_button(
                    name_row, sp_btn_text,
                    command=lambda rr=r,
                                    cell=refresh_after_action_cell:
                        self._open_sharepoint_download_dialog(
                            rr, on_close_changed=cell[0]))
            sp_btn.pack(side="right", padx=(0, 4))
            if sp_new > 0:
                _sp_tip = (f"{sp_new} new SharePoint photo(s) waiting "
                            "to be copied to OD — click to open dialog")
            elif sp_match_count > 0:
                _sp_tip = (f"{sp_match_count} SharePoint folder(s) "
                            "matched — all photos already in OD")
            else:
                _sp_tip = ("No SharePoint matches yet — click to "
                            "manually pin a folder")
            attach_tooltip(sp_btn, _sp_tip)

            # Notes button — opens Job Notes panel. Checks both legacy
            # persistence notes AND the new .md store under
            # %APPDATA%\EMS Automation\notes\.
            try:
                from job_notes_gui import (has_note as _jn_has_note,
                                            has_any_note_for_client
                                                as _jn_has_any_note,
                                            load_note as _jn_load_note,
                                            find_any_note_for_client
                                                as _jn_find_any_note,
                                            parse_stages as _jn_parse_stages,
                                            _notes_path as _jn_notes_path)
            except Exception:
                _jn_has_note = lambda *_: False
                _jn_has_any_note = lambda *_: False
                _jn_load_note = lambda *_: ""
                _jn_find_any_note = lambda *_: (None, "")
                _jn_parse_stages = lambda _t: []
                _jn_notes_path = lambda *_: ""
            _year_for_check = extract_job_year(r.get("path"))
            # Use the cross-year check so a note saved under any year shows
            # the dark icon — the popover does the same lookup, so the two
            # are guaranteed to agree.
            has_note_any = (persistence.has_note(client_name)
                            or _jn_has_any_note(client_name))
            # Latest stage badge — when a note exists, parse it for stage
            # keywords (Initial, Mold Prep, Demo, Reinspection, etc.) and
            # surface the most recent one inline. Tells the auditor at a
            # glance "this job's note says Demo", which they then check
            # against the photo-folder state on the same row.
            latest_stage = ""
            stage_age_days = None
            if has_note_any:
                try:
                    note_text = _jn_load_note(_year_for_check, client_name)
                    note_year = _year_for_check
                    # If nothing under the audit-derived year, walk all year
                    # folders so a carry-over job still gets the latest-stage
                    # chip + mtime age.
                    if not (note_text or "").strip():
                        _y, _t = _jn_find_any_note(client_name)
                        if _t:
                            note_text = _t
                            note_year = _y or _year_for_check
                    # Final fallback — legacy persistence note (text-only,
                    # mtime unknown, leaves stage_age_days as None).
                    if not (note_text or "").strip():
                        note_text = persistence.get_note(client_name) or ""
                    stages = _jn_parse_stages(note_text or "")
                    if stages:
                        latest_stage = stages[-1]
                        # Note file mtime ≈ when the user last updated it,
                        # which is a decent proxy for "how recent is this
                        # stage signal." Falls back to legacy persistence
                        # path if the .md doesn't exist yet.
                        np = _jn_notes_path(note_year, client_name)
                        if os.path.isfile(np):
                            mt = datetime.fromtimestamp(os.path.getmtime(np))
                            stage_age_days = _biz_days_since(mt)
                except Exception:
                    pass
            # Use the same notepad glyph as the launcher's Job Notes tool for
            # consistency. Color differentiates "has note" (dark) from "blank"
            # (light gray) so the icon stays the same shape across states.
            note_fg = TEXT_DARK if has_note_any else "#B8B8B8"
            notes_btn = tk.Button(
                name_row, text="🗒",
                font=("Segoe UI Emoji", 11),
                bg=WHITE, fg=note_fg,
                relief="flat", padx=2, cursor="hand2",
                command=lambda c=client_name, p=r["path"]: self._open_notes_dialog(c, p))
            # Rich hover popover — timeline (latest stage emphasized) +
            # expected files for the stages reached so far. Click still
            # opens the editor; hover gives the at-a-glance read.
            def _build_notes_hover(parent,
                                    _yr=_year_for_check,
                                    _cn=client_name):
                import job_notes_gui as _jn
                _jn.build_hover_popover(parent, _yr, _cn)
            attach_rich_tooltip(notes_btn, _build_notes_hover)

            # Pack notes_btn provisionally — the final reorder pass
            # below will re-pack everything in IUQ-matching L→R order.
            notes_btn.pack(side="right", padx=(0, 2))

            # ── IUQ-matching pack order ──────────────────────────
            # The user wants the audit row's button order to match the
            # Initial Upload row's: visually L→R the action group
            # reads `Notes | Unit | PICS | Esc | OD | Make folders |
            # SP | Pin | Trello` (the audit-specific buttons sit to
            # the left of the IUQ-shared cluster).
            #
            # Tkinter packs side="right" so each subsequent .pack
            # call lands to the LEFT of prior ones. To produce the
            # desired visual L→R, iterate in REVERSE-visual order
            # below — `link_btn` first (rightmost), `notes_btn` last
            # (leftmost of the action group).
            _iuq_order = []
            # Trello popout: only included when a pin exists (it's
            # otherwise unmapped — packing an unmapped widget would
            # surface it incorrectly).
            try:
                if link_btn is not None and link_btn.winfo_ismapped():
                    _iuq_order.append(link_btn)
            except tk.TclError:
                pass
            _iuq_order.append(pin_btn)
            if flag_btn is not None:
                _iuq_order.append(flag_btn)
            if sp_btn is not None:
                _iuq_order.append(sp_btn)
            if _mk_btn is not None:
                _iuq_order.append(_mk_btn)
            if open_dir_btn is not None:
                _iuq_order.append(open_dir_btn)
            # Audit-specific cluster (left of the shared one):
            if esc_btn is not None:
                _iuq_order.append(esc_btn)
            if pics_btn is not None:
                _iuq_order.append(pics_btn)
            if unit_btn is not None:
                _iuq_order.append(unit_btn)
            _iuq_order.append(notes_btn)
            for _w in _iuq_order:
                try:
                    _w.pack_forget()
                    _w.pack(side="right", padx=(0, 4))
                except tk.TclError:
                    pass
            if latest_stage:
                age_str = (f" · {stage_age_days}d"
                           if stage_age_days is not None else "")
                tk.Label(name_row, text=f"{latest_stage}{age_str}",
                         font=("Segoe UI Variable", 7),
                         bg=WHITE, fg=TEXT_GRAY
                         ).pack(side="right", padx=(0, 2))

            # Trello checklist progress chip — populated by the IUQ
            # scan (which already fetches checklists) and read here
            # from `persistence.trello_checklist_progress`. We don't
            # fetch synchronously per audit row — would burn API
            # quota for every reload of the daily list. When no
            # cache exists for any pinned card we render nothing.
            try:
                _pinned_ids = persistence.get_trello_card_ids(
                    client_name) or []
            except Exception:
                _pinned_ids = []
            _cl_chip = None
            for _cid in _pinned_ids:
                _entry = persistence.get_checklist_progress(_cid)
                if _entry and (_entry.get("total") or 0) > 0:
                    _cl_chip = _entry
                    break
            if _cl_chip:
                _done = int(_cl_chip.get("done") or 0)
                _total = int(_cl_chip.get("total") or 0)
                _all_done = _done >= _total
                _bg = GREEN if _all_done else "#F5E5C8"
                _fg = WHITE if _all_done else "#7A5A1F"
                _txt = (f"✓ {_done}/{_total}" if _all_done
                        else f"☑ {_done}/{_total}")
                _cl_lbl = tk.Label(
                    name_row, text=f" {_txt} ",
                    font=("Segoe UI Variable", 7, "bold"),
                    bg=_bg, fg=_fg, padx=4, pady=0)
                _cl_lbl.pack(side="right", padx=(0, 2))
                try:
                    attach_tooltip(
                        _cl_lbl,
                        f"Trello checklist: {_done} of {_total} items "
                        f"complete (cached from last IUQ scan).")
                except Exception:
                    pass

            # "Done stages" chips — what kind of work this job has
            # photos for (Demo / Contents / EQ / Initial / etc.).
            # Distinct from latest_stage (which comes from the job
            # note text): these are derived from actual subfolders
            # with photos in them, so a job with both "Demo pics" and
            # "Contents/Cart 1" surfaces both chips. Sized small and
            # colored by work type so the auditor can scan vertically.
            done_stages = r.get("done_stages") or []
            if done_stages:
                _STAGE_CHIP_COLORS = {
                    "Demo":      ("#FFE9C7", "#8A5612"),
                    "Contents":  ("#E1ECFA", "#1F4E8C"),
                    "Equipment": ("#E8F5EE", "#1E7A3D"),
                    "Initial":   ("#F2EAFA", "#5C2C9D"),
                    "Mold Prep": ("#FBEAEA", "#9C2E2E"),
                    "Post Mold": ("#FBEAEA", "#9C2E2E"),
                    "Post":      ("#EDEDED", "#444444"),
                    "Reinspect": ("#FFF3CD", "#7A5C12"),
                    "Sketch":    ("#E0F3F1", "#1F706B"),
                }
                # Pack right-to-left so the visual order on screen
                # reads left-to-right in the order returned by
                # _detect_done_stages (PICS-traversal order).
                for label in reversed(done_stages):
                    bg, fg = _STAGE_CHIP_COLORS.get(label,
                                                    ("#EEEEEE", TEXT_DARK))
                    tk.Label(name_row, text=label,
                             font=("Segoe UI Variable", 7, "bold"),
                             bg=bg, fg=fg, padx=4, pady=0
                             ).pack(side="right", padx=(0, 2))

            # Find Folder button gates on whether we have a usable path
            # to open, NOT on the `found` flag. The two are usually in
            # sync, but a stale cache entry or partial result can land
            # us in a state where `found=True` and `path=""` — which
            # used to hide BOTH 📁 (gated on path) AND Find Folder
            # (gated on found), leaving the row with no way out. Gating
            # both buttons on path alone guarantees exactly one shows.
            if not r.get("path"):
                def _find_folder(r=r, card=card):
                    # Auto-resolve via Trello card desc BEFORE the picker.
                    # If the user has a Trello card pinned to this client,
                    # its desc often carries the actual filing name —
                    # commercial jobs file under property name, residential
                    # under the insured's name, and the run-doc can carry
                    # either. Trying these terms against the year-folder
                    # listing turns "Find folder" prompts into one-click
                    # confirms for the cases where the data is already there.
                    try:
                        auto = self._try_trello_folder_resolve(r["client"])
                    except Exception:
                        auto = None
                    if auto:
                        auto_path, auto_name, _y, hit_term = auto
                        msg = (f"Trello card desc suggests this folder for "
                               f"\"{r['client']}\":\n\n"
                               f"    {auto_name}\n\n"
                               f"(matched on \"{hit_term}\")\n\n"
                               f"Use this folder?")
                        if messagebox.askyesno("Auto-resolved folder",
                                                msg, parent=self):
                            self._pin_folder_and_refresh_row(
                                r["client"], auto_path)
                            return
                    path = filedialog.askdirectory(
                        title=f"Select folder for: {r['client']}",
                        initialdir=AUDIT_BASE if os.path.isdir(AUDIT_BASE)
                                   else os.path.expanduser("~"))
                    if not path:
                        return
                    # Auto-scaffold the standard EMS/DOCS + EMS/PICS
                    # tree on first resolve. New jobs the user just
                    # created in Explorer typically don't have these
                    # yet, and without them the audit walk reports
                    # "DOCS missing" / "PICS missing" on every row —
                    # noise rather than signal. Show a quick modal
                    # so the user sees something happen before the
                    # checklist re-renders.
                    prog = tk.Toplevel(self)
                    prog.title("")
                    prog.transient(self.winfo_toplevel())
                    prog.resizable(False, False)
                    prog.overrideredirect(True)
                    pf = tk.Frame(prog, bg=WHITE,
                                   highlightthickness=1,
                                   highlightbackground=BORDER,
                                   padx=24, pady=18)
                    pf.pack()
                    tk.Label(pf, text="📂  Creating job folders…",
                             font=("Segoe UI Variable", 11, "bold"),
                             bg=WHITE, fg=TEXT_DARK).pack()
                    tk.Label(pf, text=os.path.basename(path),
                             font=("Segoe UI Variable", 8),
                             bg=WHITE, fg=TEXT_GRAY).pack(pady=(4, 0))
                    # Center over the audit panel
                    self.update_idletasks()
                    px = (self.winfo_rootx()
                          + max(0, (self.winfo_width() - 280) // 2))
                    py = (self.winfo_rooty()
                          + max(0, (self.winfo_height() - 80) // 2))
                    prog.geometry(f"+{px}+{py}")
                    prog.grab_set()
                    prog.update_idletasks()
                    def _close_prog():
                        try:
                            prog.destroy()
                        except tk.TclError:
                            pass
                    created = []
                    try:
                        for sub in (os.path.join(path, "EMS"),
                                    os.path.join(path, "EMS", "DOCS"),
                                    os.path.join(path, "EMS", "PICS")):
                            if not os.path.isdir(sub):
                                try:
                                    os.makedirs(sub, exist_ok=True)
                                    created.append(sub)
                                except OSError:
                                    pass
                    except Exception:
                        pass
                    # Pin the override and refresh THIS row only — full
                    # audit re-render is overkill when only one job's
                    # folder changed. `_refresh_single_card` re-audits
                    # the single client, drops a fresh card into the same
                    # scroll slot, and leaves every other row untouched.
                    persistence.set_folder_path(r["client"], path)
                    _close_prog()
                    show_toast(self,
                               f"OD folder pinned for {r['client']}",
                               kind="info")
                    self._refresh_single_card(r["client"])
                tk.Button(name_row, text="Find Folder",
                          font=("Segoe UI Variable", 8, "bold"),
                          bg=INFO_BG, fg=INFO_FG, activebackground=INFO_HOVER,
                          relief="flat", padx=8, pady=2, cursor="hand2",
                          command=_find_folder).pack(side="right", padx=(0, 4))

                # Rename Folder — for when a tech filed the job as
                # "Antonio Garcia" but office convention is "Garcia,
                # Antonio". Renames on disk, refreshes the override
                # path so next audit finds it under the new name.
                def _rename_folder(r=r, card=card):
                    if not r.get("found") or not r.get("path"):
                        messagebox.showinfo("No folder",
                            "This row has no resolved folder yet.\n"
                            "Use Find Folder first.")
                        return
                    old_path = r["path"]
                    if not os.path.isdir(old_path):
                        messagebox.showerror("Folder gone",
                            f"The folder no longer exists:\n{old_path}")
                        return
                    parent = os.path.dirname(old_path)
                    old_name = os.path.basename(old_path)
                    new_name = simpledialog.askstring(
                        "Rename Folder",
                        f"Rename this job folder.\n\n"
                        f"Current: {old_name}\n\n"
                        f"New name (e.g. 'Garcia, Antonio'):",
                        initialvalue=old_name, parent=self)
                    if new_name is None:
                        return
                    new_name = new_name.strip()
                    if not new_name or new_name == old_name:
                        return
                    # Reject path separators and reserved chars — Windows
                    # would throw a confusing OSError otherwise.
                    bad = set('\\/:*?"<>|')
                    if any(ch in bad for ch in new_name):
                        messagebox.showerror("Invalid name",
                            'Folder name cannot contain: \\ / : * ? " < > |')
                        return
                    new_path = os.path.join(parent, new_name)
                    if os.path.exists(new_path):
                        messagebox.showerror("Already exists",
                            f"A folder named {new_name!r} already "
                            f"exists in:\n{parent}")
                        return
                    try:
                        os.rename(old_path, new_path)
                    except OSError as ex:
                        messagebox.showerror("Rename failed",
                            f"Could not rename:\n{ex}\n\n"
                            f"Close any Explorer windows or programs "
                            f"that have this folder open and try again.")
                        return
                    # Move any persisted override to the new path so
                    # next audit doesn't lose the find-folder memory.
                    try:
                        persistence.set_folder_path(r["client"], new_path)
                    except Exception:
                        pass
                    r["path"] = new_path
                    r["folder"] = new_name
                    # Update the displayed folder label inline — the
                    # name row currently reads "{client} ({old folder})".
                    for child in name_row.winfo_children():
                        try:
                            txt = child.cget("text")
                        except tk.TclError:
                            continue
                        if isinstance(txt, str) and old_name in txt:
                            try:
                                child.config(text=txt.replace(
                                    f"({old_name})", f"({new_name})"))
                            except tk.TclError:
                                pass
                            break
                    messagebox.showinfo("Renamed",
                        f"Folder renamed:\n{old_name}  →  {new_name}")

                tk.Button(name_row, text="Rename",
                          font=("Segoe UI Variable", 8, "bold"),
                          bg="#7B6FB5", fg=ON_ACCENT, activebackground="#5E5497",
                          relief="flat", padx=8, pady=2, cursor="hand2",
                          command=_rename_folder).pack(side="right", padx=(0, 4))

            if not r["flagged"]:
                return

            # Build per-item checklist:
            #   (text, color, is_docusketch, is_commercial_form,
            #    show_workcenter, is_scope, is_photo)
            # is_photo gates the colored stage chip (Demo/Mold/etc.) so
            # form rows like "Initial photo report missing" don't pick
            # up an INITIAL chip from substring matching.
            wc_for_photos = _job_uses_workcenter_for_photos(r.get("techs"))
            items = []
            for fi in (r.get("form_issues") or []):
                # Most forms come from Workcenter — link is useful. EXCEPT
                # Scope, which is generated/uploaded separately and isn't
                # available in Workcenter — it gets a "📋 Scope" build
                # button instead so the user can author one in place.
                is_scope_item = "scope" in fi.lower()
                form_uses_wc  = not is_scope_item
                items.append((fi, FLAG_RED, False,
                              _is_commercial_form(fi), form_uses_wc,
                              is_scope_item, False))
            for pi in (r.get("photo_issues") or []):
                # Photos normally only need the WC link when Fernando's
                # on the job (he uploads direct to Workcenter rather than
                # OneDrive). EXCEPTION: Initial photo rows always get
                # the WC link — auto-detection by tech name has missed
                # cases where Initial pics actually live on Workcenter,
                # so the user wants it unconditional for that row.
                # Skip for the Docusketch row either way — that has its
                # own Import button.
                is_initial_photo = "initial" in pi.lower()
                show_wc = ((wc_for_photos or is_initial_photo)
                           and "docusketch" not in pi.lower())
                # Docusketch isn't a photo-stage subfolder — leave the
                # chip off so it stays grouped with the import button.
                is_photo_row = "docusketch" not in pi.lower()
                items.append((pi, FLAG_RED,
                              "docusketch" in pi.lower(), False, show_wc,
                              False, is_photo_row))
            # Dispute / rejection notes pulled from the run-doc text. The
            # user has to clear these manually with the carrier — surface
            # them as red items so they can't slip past a "looks fine"
            # forms+photos pass.
            for ni in (r.get("note_issues") or []):
                items.append((ni, FLAG_RED, False, False, False, False, False))
            # Day-by-day photo requirements (day 2+). The existing
            # check_photos covers day 1 ("Demo pics"); once day-1 photos
            # are in, the Demo folder is non-empty so that check can't
            # tell a later Demo day still owes its own photos. This
            # tracker fills that gap — it flags "Demo day 2 photos (6/4)"
            # until a photo dated to that day lands, then auto-clears.
            # Amber (not red) since it's a per-day expectation, not a
            # hard paperwork gap.
            for req in (r.get("requirements") or []):
                if req.get("satisfied") or int(req.get("day_num", 1)) < 2:
                    continue
                try:
                    _rd = datetime.strptime(req["date"], "%Y-%m-%d")
                    _rds = f"{_rd.month}/{_rd.day}"
                except Exception:
                    _rds = req.get("date", "")
                _rtxt = f"📸 {req.get('label', 'photos')} ({_rds})"
                items.append((_rtxt, "#E67E22", False, False,
                              wc_for_photos, False, True))
            if r["aging"] >= 3 and r["found"]:
                last_str = r["last"].strftime("%m/%d/%y") if r["last"] else "never"
                items.append((f"{r['aging']}d inactive (last: {last_str})",
                              "#E67E22", False, False, False, False, False))

            if not items:
                return

            card_resolved    = [False]
            all_vars         = []
            # item_records: per-row state we revisit when an action (DS
            # import, WC import, scope save) finishes — so a single zip
            # that drops multiple files can cross off ALL the items it
            # resolved, not just the row whose button was clicked.
            # Schema: [(item_txt, var, lbl, item_color, [action_btns]), …]
            item_records = []

            has_commercial = any(ic for _, _, _, ic, _, _, _ in items)
            commercial = CommercialToggle(name_row, r["client"],
                                          bg=WHITE, activebackground=WHITE,
                                          selectcolor=WHITE)
            if has_commercial:
                commercial.checkbutton.pack(side="right", padx=(0, 4))

            def _make_toggle(var, lbl, item_color, all_v, bl, ca, cr,
                             client=None, issue=None):
                def _toggle():
                    if var.get():
                        lbl.config(fg=TEXT_MUTED,
                                   font=("Segoe UI Variable", 8, "overstrike"))
                    else:
                        lbl.config(fg=item_color,
                                   font=("Segoe UI Variable", 8))
                    if client and issue:
                        persistence.set_resolved(self.run_date, client,
                                                  persist_key(issue), var.get())
                    now_done = all(v.get() for v in all_v)
                    was_done = cr[0]
                    if now_done and not was_done:
                        cr[0] = True
                        bl.config(text=" OK ", bg=GREEN)
                        ca.config(highlightbackground=GREEN)
                        resolved[0] += 1
                        _update_status()
                    elif not now_done and was_done:
                        cr[0] = False
                        bl.config(text="FLAG", bg=FLAG_RED)
                        ca.config(highlightbackground=BORDER)
                        resolved[0] -= 1
                        _update_status()
                return _toggle


            # Body container — virtualized via VirtualizedCardList:
            # issue rows packed below get destroyed when this card
            # scrolls outside the viewport's overscan band, and
            # rebuilt when it scrolls back in. Drops the live HWND
            # child count Tk has to reposition during scroll, which
            # is the root cause of scroll tearing on a card-heavy
            # panel. Persistent state (card_resolved, persistence
            # checkbox values) lives outside _build_body so the
            # badge OK/FLAG state survives derealize/realize.
            body = tk.Frame(detail, bg=WHITE)
            body.pack(fill="x")

            def _build_body(body_frame):
                # Reset per-build state. all_vars/item_records live
                # at the card scope so post-build checks (auto-OK
                # flip) can see them; we mutate via clear()/append()
                # to keep the same list object referenced by any
                # closures still holding it from the prior build.
                commercial.toggles = []
                all_vars.clear()
                item_records.clear()

                def _refresh_card_after_action(rr=r, recs=item_records,
                                               av=all_vars, bl=badge_lbl,
                                               ca=card, cr=card_resolved,
                                               pb=pics_btn, sb=sp_btn):
                    """Re-walk this job's folder after an in-place action (DS
                    import, WC import, scope save, SP copy) and cross off
                    items that are no longer flagged on disk. Catches the
                    case where one Workcenter zip drops multiple forms — the
                    clicked row would update via its own success path, but
                    sibling rows used to stay flagged until a full re-audit.
                    Action buttons on auto-resolved rows are also hidden.

                    Two-phase to keep the UI snappy:
                      Phase 1 (sync, instant) — hide the 📥 SP +N pill and
                        zero rr["sharepoint_new"]. No disk work, fires the
                        moment the dialog finishes destroying.
                      Phase 2 (threaded) — walk the job folder to refresh
                        the form/photo flag set, recount photos under PICS,
                        then bounce the visual updates (📷 N pill,
                        cross-offs, card status) back to the main thread.
                        The os.walk over a OneDrive-synced PICS tree can
                        take seconds because OneDrive pulls metadata from
                        the cloud — running it on the UI thread froze the
                        dialog close. Threading restores the snappy feel.
                    """
                    # ── Phase 1: instant visual ack ───────────────────────
                    # The SP pill stays visible after a copy/mark — the
                    # user explicitly asked for the dialog to be
                    # reopenable even when there's nothing new to copy.
                    # Just restyle the button to reflect the new state
                    # (no "+N new" once N drops to zero) instead of
                    # hiding it.
                    rr["sharepoint_new"] = 0
                    if sb is not None:
                        new_match_count = len(rr.get("sharepoint_matches") or [])
                        try:
                            # Label-only update — the button now uses the
                            # shared link_button styling so we don't
                            # re-apply per-state colors; the count in
                            # the text is the entire signal.
                            if new_match_count > 0:
                                sb.config(
                                    text=f"📁 SP ({new_match_count})")
                            else:
                                sb.config(text="📁 SP")
                        except tk.TclError:
                            pass

                    cp_rr = rr.get("path")
                    if not cp_rr or not os.path.isdir(cp_rr):
                        return

                    # ── Phase 2: deferred disk walk ───────────────────────
                    def _walk_and_diff():
                        try:
                            ems  = os.path.join(cp_rr, "EMS")
                            cont = os.path.join(cp_rr, "CONTENTS")
                            base = (ems if os.path.isdir(ems)
                                    else (cont if os.path.isdir(cont)
                                          else cp_rr))
                            fresh_forms  = set(check_forms(base) or [])
                            fresh_photos = set(
                                (check_docusketch(base) or []) +
                                (check_photos(resolve_pics_dir(base)) or []))
                            pics_path_new = resolve_pics_dir(base)
                            pics_count_new = 0
                            if pics_path_new and os.path.isdir(pics_path_new):
                                try:
                                    for _root, _dirs, _files in os.walk(
                                            pics_path_new):
                                        pics_count_new += len(_files)
                                except OSError:
                                    pics_count_new = rr.get("pics_count", 0)
                        except Exception:
                            return
                        self.after(
                            0,
                            lambda: _apply_walk_results(
                                fresh_forms, fresh_photos, pics_count_new))

                    def _apply_walk_results(fresh_forms, fresh_photos,
                                             pics_count_new):
                        still_flagged = fresh_forms | fresh_photos
                        rr["pics_count"] = pics_count_new
                        if pb is not None:
                            if pics_count_new > 0:
                                new_bg, new_fg = "#E8F5EE", GREEN_DARK
                            else:
                                new_bg, new_fg = "#FBEAE5", "#A04025"
                            try:
                                pb.config(text=f"📷 {pics_count_new}",
                                          bg=new_bg, fg=new_fg,
                                          activebackground=new_bg)
                            except tk.TclError:
                                pass
                        _cross_off_resolved(still_flagged)

                    threading.Thread(target=_walk_and_diff,
                                     daemon=True).start()

                def _cross_off_resolved(still_flagged,
                                         rr=r, recs=item_records,
                                         av=all_vars, bl=badge_lbl,
                                         ca=card, cr=card_resolved):
                    # Snapshot which items were flagged at audit time so we
                    # only auto-resolve form/photo issues — aging-/note-
                    # issues live on different axes that disk-walking can't
                    # answer ("3d inactive" doesn't go away because a form
                    # showed up).
                    originally_flagged = set(
                        (rr.get("form_issues") or []) +
                        (rr.get("photo_issues") or []))
                    changed = False
                    for (item_txt, var, lbl_w, item_color, btns) in recs:
                        if var.get():
                            continue  # already resolved
                        if item_txt not in originally_flagged:
                            continue  # not a disk-resolvable item
                        if item_txt in still_flagged:
                            continue  # still missing on disk
                        var.set(True)
                        try:
                            lbl_w.config(fg=TEXT_MUTED,
                                         font=("Segoe UI Variable", 8, "overstrike"))
                        except tk.TclError:
                            pass
                        try:
                            persistence.set_resolved(self.run_date,
                                                      rr["client"],
                                                      persist_key(item_txt),
                                                      True)
                        except Exception:
                            pass
                        for b in btns:
                            try:
                                if b.winfo_ismapped():
                                    b.pack_forget()
                            except Exception:
                                pass
                        changed = True
                    if changed and all(v.get() for v in av) and not cr[0]:
                        cr[0] = True
                        try:
                            bl.config(text=" OK ", bg=GREEN)
                            ca.config(highlightbackground=GREEN)
                        except tk.TclError:
                            pass
                        resolved[0] += 1
                        _update_status()

                # Publish the helper to the cell so the (already-built) SP
                # button up in the name_row can pass it through to the SP
                # dialog as on_close_changed without forward-ref headaches.
                refresh_after_action_cell[0] = _refresh_card_after_action

                for (item_txt, item_color, is_ds, is_comm, show_wc, is_scope,
                     is_photo) in items:
                    already = persistence.is_resolved(self.run_date, r["client"],
                                                        persist_key(item_txt))
                    # Carry-forward: even if not resolved for today's run_date,
                    # if the user marked this same item resolved within the
                    # last 7 days, pre-check it. The audit re-flagged it
                    # because the underlying form/photo is still missing on
                    # disk — but the user already addressed it, and we want
                    # them to only have to ACT on what's genuinely new.
                    # Stamp the prior date inline so the user can tell which
                    # items are carry-forward vs fresh.
                    carry_date = None
                    if not already:
                        try:
                            carry_date = persistence.last_resolved_within(
                                r["client"], persist_key(item_txt), days=7)
                        except Exception:
                            carry_date = None
                        if carry_date:
                            already = True
                    var = tk.BooleanVar(value=already)
                    all_vars.append(var)
                    item_row = tk.Frame(body_frame, bg=WHITE)
                    item_row.pack(fill="x", pady=1)

                    # Stage chip — only on photo rows. Lets the eye jump to
                    # which stage of the job (Demo, Mold Prep, Abatement, …)
                    # is missing photos without parsing every "X pics" string.
                    chip = _photo_stage_chip(item_txt) if is_photo else None
                    if chip:
                        chip_label, chip_bg = chip
                        tk.Label(item_row, text=f" {chip_label} ",
                                 font=("Segoe UI Variable", 7, "bold"),
                                 bg=chip_bg, fg=WHITE,
                                 padx=2, pady=0
                                 ).pack(side="left", padx=(2, 4))

                    # Workcenter heads-up — Fernando/FB upload photos straight
                    # to Workcenter, so a "missing photo" row that's actually
                    # in WC isn't really missing. Only show the tag when the
                    # row WON'T also get a "📥 WC photos" button (i.e. when
                    # WORKCENTER_URL is unset) — otherwise the button itself
                    # is the signal and the tag is redundant noise.
                    will_have_wc_button = bool(show_wc and WORKCENTER_URL)
                    if is_photo and wc_for_photos and not will_have_wc_button:
                        tk.Label(item_row, text=" WC ",
                                 font=("Segoe UI Variable", 7, "bold"),
                                 bg="#7B5BA8", fg=ON_ACCENT,
                                 padx=2, pady=0
                                 ).pack(side="left", padx=(0, 4))

                    lbl = tk.Label(item_row, text=item_txt,
                                   font=("Segoe UI Variable", 8 if not already else 8),
                                   bg=WHITE,
                                   fg=TEXT_MUTED if already else item_color,
                                   anchor="w")
                    if already:
                        lbl.config(font=("Segoe UI Variable", 8, "overstrike"))
                    lbl.pack(side="left", padx=(2, 0))
                    # Carry-forward hint — small badge next to the label
                    # showing the prior run_date when the user marked this
                    # done. Lets them spot "this was already addressed" at
                    # a glance vs items that are genuinely fresh today.
                    if carry_date:
                        try:
                            from datetime import datetime as _dt
                            d = _dt.strptime(carry_date, "%m-%d-%Y")
                            carry_lbl_text = f"↻ {d.strftime('%-m/%-d')}" \
                                if os.name != "nt" else f"↻ {d.month}/{d.day}"
                        except Exception:
                            carry_lbl_text = f"↻ {carry_date}"
                        tk.Label(item_row, text=carry_lbl_text,
                                 font=("Segoe UI Variable", 7), bg=WHITE,
                                 fg="#7B6FB5"
                                 ).pack(side="left", padx=(4, 0))
                    # 📨 Requested chip — visible signal that the user has
                    # already chased this item on Trello so they don't
                    # request the same form twice. Data backs onto the
                    # existing `audit_comments` persistence table that the
                    # 💬 button already writes to (mark_audit_comment_posted).
                    # Color escalates with age: green (today), amber (1-3d),
                    # red (4d+ — chase again or escalate). _refresh_request_chip
                    # is captured by the 💬 click handler so the chip
                    # appears immediately after a comment posts, not just
                    # on the next audit re-run.
                    req_chip = tk.Label(item_row, text="",
                                          font=("Segoe UI Variable", 7, "bold"),
                                          bg=WHITE, fg=WHITE,
                                          padx=4, pady=0)

                    def _refresh_request_chip(chip=req_chip,
                                                client=r["client"],
                                                issue=item_txt):
                        try:
                            issue_k = persist_key(issue)
                            posted_date = persistence.get_audit_comment_date(
                                client, issue_k)
                        except Exception:
                            posted_date = ""
                        if not posted_date:
                            try:
                                chip.pack_forget()
                            except tk.TclError:
                                pass
                            return
                        # Age in days since the post — escalating color.
                        try:
                            from datetime import datetime as _rdt
                            d = _rdt.strptime(posted_date, "%m-%d-%Y")
                            age_days = max(
                                0,
                                (_rdt.today().date() - d.date()).days)
                        except Exception:
                            age_days = 0
                        age_lbl = ("today" if age_days == 0 else
                                    f"{age_days}d ago")
                        if age_days <= 0:
                            bg_c, fg_c = SUCCESS_BG, SUCCESS_FG
                        elif age_days <= 3:
                            bg_c, fg_c = WARN_HOVER, WARN_FG
                        else:
                            bg_c, fg_c = DANGER_BG, DANGER_FG
                        try:
                            chip.config(
                                text=f"📨 Requested {age_lbl}",
                                bg=bg_c, fg=fg_c)
                            if not chip.winfo_ismapped():
                                chip.pack(side="left", padx=(4, 0))
                        except tk.TclError:
                            pass
                        try:
                            attach_tooltip(
                                chip,
                                f"Comment posted {posted_date}. The 💬 "
                                "button greys out for 3 days to prevent "
                                "duplicate nags — click anyway to chase "
                                "again.")
                        except Exception:
                            pass
                    _refresh_request_chip()
                    toggle_fn = _make_toggle(var, lbl, item_color, all_vars,
                                             badge_lbl, card, card_resolved,
                                             client=r["client"], issue=item_txt)
                    # Action buttons on this row — collected so _wrapped_toggle
                    # can hide ALL of them (not just WC) when the item resolves.
                    row_action_btns = []
                    # Captured by reference so the closure below sees buttons
                    # appended AFTER it was defined (DS / Scope / WC are
                    # added in sequence). Used by every import-success path
                    # to hide the now-redundant action buttons; checkbox
                    # set via var.set(True) doesn't fire the Checkbutton's
                    # `command`, so without this the button stays visible
                    # even though the item is ticked off.
                    def _hide_row_btns(btns=row_action_btns):
                        for b in btns:
                            try:
                                if b.winfo_ismapped():
                                    b.pack_forget()
                            except Exception:
                                pass
                    def _on_import_success(refresh=_refresh_card_after_action,
                                            hide=_hide_row_btns):
                        hide()
                        try:
                            refresh()
                        except Exception:
                            pass
                    if is_ds and r["path"]:
                        # 📐 Requested chip — appears when the user has
                        # already clicked "Request via Trello" for this
                        # job's Docusketch. Keeps the audit row honest:
                        # "I already chased this" is one glance, not a
                        # checkbox-vs-trello-card cross-reference. Auto-
                        # disappears when the docusketch zip imports
                        # (resolve() runs inside the import flow).
                        try:
                            import docusketch_requests as _dr
                            _ds_card = persistence.get_trello_card_id(
                                r["client"]) or ""
                            _ds_entry = (
                                _dr.pending_requests() if _ds_card else [])
                            _ds_match = next(
                                (e for e in _ds_entry
                                 if e.get("card_id") == _ds_card), None)
                        except Exception:
                            _ds_match = None
                        if _ds_match:
                            _days = int(_ds_match.get("days_pending") or 0)
                            _age_txt = (f"{_days}d ago"
                                         if _days > 0 else "today")
                            _req_chip = tk.Label(
                                item_row,
                                text=f"📐 Requested {_age_txt}",
                                font=("Segoe UI Variable", 7, "bold"),
                                bg=WARN_HOVER, fg=WARN_FG,
                                padx=5, pady=1)
                            _req_chip.pack(side="left", padx=(4, 0))
                            try:
                                attach_tooltip(
                                    _req_chip,
                                    "Docusketch was requested on this "
                                    "card. Clears automatically when the "
                                    "zip is imported.")
                            except Exception:
                                pass
                        # Per-item-row buttons stay compact (font=7
                        # bold, padx=4, pady=1) — the name_row buttons
                        # at the top of the card are the IUQ-sized
                        # ones. Mixing sizes within the card surfaces
                        # the visual hierarchy: card-level actions are
                        # prominent, per-item actions are tighter.
                        ds_btn = link_button(
                            item_row, "📥 Import",
                            padx=4, pady=1,
                            font=("Segoe UI Variable", 7, "bold"),
                            command=_make_import_action(
                                r["path"], var, lbl,
                                all_vars, badge_lbl,
                                card, card_resolved,
                                on_success=_on_import_success,
                                client_name=r.get("client", "")))
                        ds_btn.pack(side="left", padx=(4, 0))
                        row_action_btns.append(ds_btn)
                    if is_scope and r["path"]:
                        # Scope isn't on Workcenter — give a build-in-place button
                        # that opens the paste-and-save dialog, then ticks this
                        # row off when the PDF lands in EMS/DOCS.
                        def _make_scope_action(client=r["client"], path=r["path"],
                                                v=var, l=lbl, all_v=all_vars,
                                                bl=badge_lbl, ca=card,
                                                cr=card_resolved, issue=item_txt):
                            def _on_saved(_out, hide=_hide_row_btns):
                                v.set(True)
                                l.config(fg=TEXT_MUTED,
                                         font=("Segoe UI Variable", 8, "overstrike"))
                                persistence.set_resolved(self.run_date, client,
                                                          persist_key(issue), True)
                                if all(vv.get() for vv in all_v) and not cr[0]:
                                    cr[0] = True
                                    bl.config(text=" OK ", bg=GREEN)
                                    ca.config(highlightbackground=GREEN)
                                    resolved[0] += 1
                                    _update_status()
                                hide()
                                # Also re-walk in case the scope save resolved
                                # sibling rows (e.g. authoring scope often comes
                                # with the techs dropping initial photos right
                                # after, and we want those to update too).
                                _refresh_card_after_action()
                            def _do():
                                open_scope_dialog(self, client, path,
                                                   on_saved=_on_saved)
                            return _do
                        scope_btn = tk.Button(
                            item_row, text="📋 Scope",
                            font=("Segoe UI Variable", 7), bg="#8E44AD", fg=ON_ACCENT,
                            activebackground="#6C3483", relief="flat",
                            padx=4, pady=1, cursor="hand2",
                            command=_make_scope_action())
                        scope_btn.pack(side="left", padx=(4, 0))
                        row_action_btns.append(scope_btn)
                    # 💬 Comment to Trello — one-click templated nag on
                    # the pinned card for this client. Greyed out + tooltip
                    # when a comment for the same client+issue was posted
                    # in the last 3 days, so re-running the audit doesn't
                    # spam the same nag.
                    try:
                        _pinned_ids = persistence.get_trello_card_ids(
                            r["client"]) or []
                    except Exception:
                        _pinned_ids = []
                    if _pinned_ids:
                        issue_key = persist_key(item_txt)
                        try:
                            recent_d = persistence.get_audit_comment_date(
                                r["client"], issue_key)
                            posted_recently = (
                                persistence.audit_comment_posted_within(
                                    r["client"], issue_key, days=3))
                        except Exception:
                            recent_d = ""
                            posted_recently = False

                        def _make_comment_action(client=r["client"],
                                                  issue_txt=item_txt,
                                                  key=issue_key,
                                                  ids=tuple(_pinned_ids),
                                                  refresh_chip=_refresh_request_chip):
                            def _do():
                                self._post_audit_comment_to_trello(
                                    client, issue_txt, key, ids)
                                # Repaint the "📨 Requested" chip without
                                # waiting for the next audit run — the
                                # post call already wrote the date to
                                # persistence on success.
                                try:
                                    refresh_chip()
                                except Exception:
                                    pass
                            return _do

                        comment_btn = tk.Button(
                            item_row, text="💬",
                            font=("Segoe UI Variable", 8),
                            bg=(SURFACE_2 if posted_recently else LINK_BG),
                            fg=(TEXT_MUTED if posted_recently else LINK_FG),
                            activebackground=LINK_HOVER,
                            relief="flat", padx=4, pady=0, cursor="hand2",
                            command=_make_comment_action())
                        comment_btn.pack(side="right", padx=(0, 2))
                        try:
                            from tool_panel import attach_tooltip
                            if posted_recently and recent_d:
                                attach_tooltip(
                                    comment_btn,
                                    f"Last commented {recent_d} — "
                                    f"click to comment again anyway.")
                            else:
                                attach_tooltip(
                                    comment_btn,
                                    "Post a templated comment about this "
                                    "finding on the pinned Trello card.")
                        except Exception:
                            pass

                    # 📥 Import — unified scanner that auto-routes the
                    # zip in Downloads to the right importer (WC docs /
                    # WC photos / DocuSign packet). Replaces the
                    # earlier 📥 WC docs + 📝 DS pair: the user wanted
                    # a single button that "scans and pulls in whatever
                    # we downloaded regardless." On rows where multiple
                    # kinds are valid AND multiple zips are present in
                    # Downloads, a small picker dialog disambiguates.
                    is_photo_item = item_txt in (r.get("photo_issues") or [])
                    is_form_item = item_txt in (r.get("form_issues") or [])
                    is_ds_signable = is_form_item and any(
                        kw in (item_txt or "").lower()
                        for kw in ("auth", "atp",
                                   "customer info", "cif",
                                   "customer equip", "cer",
                                   "cert of satisf", "cos"))
                    can_show_import = (
                        (show_wc and WORKCENTER_URL)
                        or (is_ds_signable and r["path"]))
                    smart_btn = None
                    if can_show_import:
                        smart_btn = link_button(
                            item_row, "📥 Import",
                            padx=4, pady=1,
                            font=("Segoe UI Variable", 7, "bold"),
                            command=_make_smart_import_action(
                                r["path"], var, lbl, all_vars, badge_lbl,
                                card, card_resolved,
                                item_txt=item_txt,
                                client_name=r["client"],
                                is_photo=is_photo_item,
                                is_ds_signable=bool(
                                    is_ds_signable and r["path"]),
                                show_wc=bool(show_wc and WORKCENTER_URL),
                                on_success=_on_import_success))
                        if not already:
                            smart_btn.pack(side="left", padx=(4, 0))
                        row_action_btns.append(smart_btn)
                        try:
                            attach_tooltip(
                                smart_btn,
                                "Scans your Downloads folder and "
                                "imports whatever zip we find — "
                                "Workcenter docs / photos OR DocuSign "
                                "signed packet. If multiple options "
                                "are in Downloads, you'll get a small "
                                "picker.")
                        except Exception:
                            pass

                    if is_ds_signable and r["path"]:
                        # ✍ Requested chip — surfaces when the user has
                        # already requested DocuSign via the Hygiene right-
                        # click flow or this row's dialog. Auto-disappears
                        # once import completes (resolve() fires in the
                        # import success path). Mirrors the docusketch
                        # "📐 Requested Nd ago" chip placement.
                        try:
                            import docusign_requests as _dsr
                            _dsign_pending = _dsr.pending_requests()
                            _client_low = (r.get("client") or "").lower()
                            _dsign_match = next(
                                (e for e in _dsign_pending
                                 if (e.get("client") or "").lower()
                                     == _client_low),
                                None)
                        except Exception:
                            _dsign_match = None
                        if _dsign_match:
                            _ds_days = int(
                                _dsign_match.get("days_pending") or 0)
                            _ds_age_txt = (f"{_ds_days}d ago"
                                            if _ds_days > 0 else "today")
                            _ds_state = _dsign_match.get("state") or ""
                            _chip_text = (
                                "✍ Requested " + _ds_age_txt
                                if _ds_state == "pending_signature"
                                else "✉ Awaiting email " + _ds_age_txt)
                            _dsign_chip = tk.Label(
                                item_row,
                                text=_chip_text,
                                font=("Segoe UI Variable", 7, "bold"),
                                bg=WARN_HOVER, fg=WARN_FG,
                                padx=5, pady=1)
                            _dsign_chip.pack(side="left", padx=(4, 0))
                            try:
                                _tip = ("DocuSign was requested on this "
                                        "card. Clears automatically when "
                                        "the signed packet is imported."
                                        if _ds_state == "pending_signature"
                                        else "Waiting on an email "
                                             "address from the office "
                                             "before DocuSign can be "
                                             "sent.")
                                attach_tooltip(_dsign_chip, _tip)
                            except Exception:
                                pass
                        # NOTE: the dedicated 📝 DS button was retired —
                        # the unified 📥 Import button above scans
                        # Downloads for WC docs / WC photos / DocuSign
                        # packets in one go and routes to the right
                        # importer. The ✍ Requested chip directly above
                        # remains useful (shows pending-request state).

                    # Wrap the toggle so it also hides all action buttons on
                    # this row — once the item is checked off, every fetch/
                    # build button is moot. Used to hide just the WC button;
                    # extended to also hide the DS Import and Scope buttons.
                    base_toggle = toggle_fn
                    def _wrapped_toggle(v=var, btns=tuple(row_action_btns),
                                        base=base_toggle):
                        base()
                        if v.get():
                            for b in btns:
                                try:
                                    if b.winfo_ismapped():
                                        b.pack_forget()
                                except Exception:
                                    pass
                        else:
                            # User unchecked — restore any previously-hidden
                            # buttons that should still be available.
                            for b in btns:
                                try:
                                    if not b.winfo_ismapped():
                                        b.pack(side="left", padx=(4, 0))
                                except Exception:
                                    pass
                    toggle_fn = _wrapped_toggle

                    # Record this row for the post-action card re-walk so a
                    # sibling row that the same zip resolved can also be
                    # crossed off without re-running the full audit.
                    item_records.append((item_txt, var, lbl, item_color,
                                         row_action_btns))

                    if is_comm:
                        commercial.register(var, toggle_fn,
                                            persist_key(item_txt))

                    tk.Checkbutton(item_row, variable=var, bg=WHITE,
                                   activebackground=WHITE, selectcolor=WHITE,
                                   command=toggle_fn
                                   ).pack(side="right")

                # Sticky-Commercial auto-apply: cascade once if the master
                # checkbox loaded True from persistence (the master command
                # does NOT fire on init).
                commercial.auto_apply_if_sticky()

                # If every item for this card was already resolved from a prior session,
                # flip badge to OK and update totals
                if (all_vars and all(v.get() for v in all_vars)
                        and not card_resolved[0]):
                    card_resolved[0] = True
                    badge_lbl.config(text=" OK ", bg=GREEN)
                    card.config(highlightbackground=GREEN)
                    resolved[0] += 1
                    _update_status()

                # Always re-paint the status line after each card so the
                # streaming "X jobs · Y flagged · Z OK" tally updates as
                # the worker thread feeds results in. Cheap (one CTk
                # configure) and means the user sees the count climb.
                if streaming:
                    _update_status()

                # In Progress - ADMIN Trello checklist, inline below the
                # card's items — lets the user tick demo photos / order
                # docusketch / etc. by hand without leaving the audit.
                try:
                    self._attach_inprogress_checklist(body_frame, r["client"])
                except Exception:
                    pass

            _build_body(body)
            # Register so subsequent scrolls that move this card
            # outside the overscan band derealize its body. The
            # initial paint above must come BEFORE register so the
            # virtualizer's first visibility tick treats the card
            # as already-realized at its full height.
            self._virt_cards.register(body, _build_body)

        # Expose the per-card closure on self so `_refresh_single_card`
        # can rebuild one row without re-running this whole `_render`.
        # Streaming mode also uses this hook; the closure handles both.
        self._render_one_card_fn = _render_one_card

        # ── Streaming setup hook ────────────────────────────────────
        # In streaming mode we just stash the per-card closure on self
        # and return — the worker thread in _run_audit will call
        # `self._streaming_render_one(r)` per arrival.
        if streaming:
            self._streaming_render_one = _render_one_card
            return

        # ── Batch mode: iterate all results synchronously ────────────
        for r in results:
            _render_one_card(r)
        # Pick up any inline tk.Button widgets the per-card render didn't
        # already give an explicit tooltip — covers icon-cluster items
        # (FLAG/OK, NEW LOSS, time-slot, etc.) with default hover hints
        # derived from their text via tool_panel.ICON_TOOLTIPS.
        self.after_idle(self.sweep_tooltips)


def main(argv=None):
    run_standalone(RunAuditApp, geometry="640x600")


if __name__ == "__main__":
    main()
