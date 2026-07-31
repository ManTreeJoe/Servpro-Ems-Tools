"""
APA Monitor — track jobs throughout the day and save as a .docx
at X:\\IE_Public\\APA Monitor\\<Year>\\<Month>\\<M-D-Weekday> .docx

Sections mirror the existing APA doc format (Final Uploads, Pending Review
per estimator, Initial/Daily Uploads, Audit Rejection/Dispute, etc.).
"""
import os
import re
import sys
import json
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import RGBColor, Pt, Inches


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import ctk_helpers as ctkh
import paths
import persistence
from theme import (GREEN, GREEN_DARK, GREEN_LIGHT, WHITE, BG,
                     TEXT_DARK, TEXT_GRAY, TEXT_MUTED, BORDER, FLAG_RED,
                     SURFACE_2, NEUTRAL_HOVER,
                     SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
                     INFO_FG,
                     LINK_BG, LINK_FG,
                     WARN_BG, WARN_FG,
                     DANGER_BG, DANGER_FG,
                     SPACE_XS, SPACE_S, SPACE_M, SPACE_L, SPACE_XL)
from tool_panel import (ToolPanel, run_standalone, show_toast, notify_error,
                         ResponsiveActionBar, ScrollableFrame, ResponsiveSnap,
                         attach_tooltip)
from ui_buttons import (done_button, send_button, link_button,
                          secondary_button, warn_button, danger_button,
                          icon_button)

# Lives in config.json so a different deployment (e.g. test machine
# pointing at a local copy) can override without code edits. Falls back
# to the legacy hardcoded path if the key is missing from older configs.
# APA logic (section model, doc parse/write, text normalizers) lives in the
# UI-free apa_logic module, shared with apa_web. Re-export the names this
# module + its callers use so the Tk UI and external importers are unaffected.
# parse_existing_doc/write_doc now accept an optional section_order, defaulting
# to the persisted order. See EMS_Tk_Extraction_Plan.md.
from apa_logic import (  # noqa: E402
    APA_ROOT,
    _ITEM_FONT_SIZE, _EXTENDED_RED, _NUM_PREFIX_RE,
    SEC_FINAL_UPLOADS, SEC_EST_MISSING, SEC_EST_SERVICE_CALL, SEC_EST_TBA,
    SEC_EST_SNAPSHOT, SEC_PENDING_REVIEW, SEC_PENDING_REVIEW_DOC,
    SEC_INITIAL_UPLOADS, SEC_DAILY_UPLOADS, SEC_AUDIT_REJECTION,
    SEC_AUDIT_DISPUTE,
    _DEFAULT_ESTIMATORS_ORDERED, _BUILTIN_SECTIONS, _BUILTIN_SET,
    _DEFAULT_SECTION_ORDER, _persisted_section_order, _estimators_from_order,
    _FRANCHISE_PAREN_RE, _franchise_key, WEEKDAY_SPELLING, doc_path_for_today,
    SUB_OPTIONS, _FINAL_UPLOAD_EXTRAS, _INITIAL_DAILY_EXTRAS,
    _STATUS_TRAILINGS, _SUB_TRAILINGS, _ALL_TRAILINGS,
    HIGHLIGHT_STATUSES, _ALL_STATUS_VARIANTS, strip_status_from_text,
    parse_existing_doc, write_doc,
    # Stateless dropdown/role/Teams helpers — moved to apa_logic, shimmed
    # here so the Tk UI + tests keep working unchanged. The mutable
    # section-order cache (SECTION_ORDER / ESTIMATORS_ORDERED /
    # ESTIMATOR_SECTIONS / _reload_estimators_cache) and the cache-coupled
    # _sub_options_for_section stay LOCAL below (this module reads them as
    # locals + reloads them locally).
    SUB_SECTIONS, AUDIT_SECTIONS, STATUS_OPTIONS, AUDIT_STATUS_OPTIONS,
    _status_options_for_section, open_teams_chat, estimator_first_name,
)
_ICON    = paths.resource("wrench.ico")

# Section model (SEC_* names, builtin set, default order, the persisted-order
# resolver, and _estimators_from_order) now lives in apa_logic and is
# re-exported via the shim import above.

# Module-level cache populated on first read so accessor calls don't
# hit persistence on every dropdown lookup. `_reload_estimators_cache`
# is called from the Manage Sections dialog after a save.
SECTION_ORDER = _persisted_section_order()
ESTIMATORS_ORDERED = _estimators_from_order(SECTION_ORDER)


def _reload_estimators_cache():
    """Refresh SECTION_ORDER + ESTIMATORS_ORDERED + ESTIMATOR_SECTIONS.
    Called after the Manage Sections dialog saves a new order. Name
    kept for backwards compatibility — it now reloads the FULL section
    order, not just the estimator slice."""
    global ESTIMATORS_ORDERED, SECTION_ORDER, ESTIMATOR_SECTIONS
    SECTION_ORDER = _persisted_section_order()
    ESTIMATORS_ORDERED = _estimators_from_order(SECTION_ORDER)
    ESTIMATOR_SECTIONS = set(ESTIMATORS_ORDERED)


# ESTIMATOR_SECTIONS is the mutable estimator set — stays local because
# _reload_estimators_cache rebinds it. SUB_SECTIONS + AUDIT_SECTIONS are
# constants, now shimmed from apa_logic (import above).
ESTIMATOR_SECTIONS = set(ESTIMATORS_ORDERED)


def _estimator_initials(name: str) -> str:
    """Display label for the estimator chip row. Single-word names show
    up to 4 chars ("AARON" → "AARO", "ZAC" → "ZAC"). Multi-word names
    use first letter of each word ("AARON L" → "AL"). Initials win
    when the name has a space because the chip strip gets crowded
    fast on a wide roster."""
    s = (name or "").strip().upper()
    if not s:
        return "?"
    parts = s.split()
    if len(parts) > 1:
        return "".join(p[0] for p in parts if p)
    return s if len(s) <= 4 else s[:4]

# STATUS_OPTIONS + AUDIT_STATUS_OPTIONS now live in apa_logic (shim above).

# SUB_OPTIONS, the status/sub trailing-string lists, HIGHLIGHT_STATUSES and
# _ALL_STATUS_VARIANTS now live in apa_logic (re-exported via the shim import
# above) alongside strip_status_from_text, which parses them back out.


def _sub_options_for_section(section):
    """Return the list for the first dropdown, or None to hide it.

    Final/Initial/Daily Uploads share most of SUB_OPTIONS but each has a
    section-specific tail value: Final gets 'Completed - Work Performed'
    (only meaningful for closed-out jobs), Initial+Daily get 'TBA' (used
    when a job hasn't been assigned yet)."""
    if section in AUDIT_SECTIONS:
        return [""] + ESTIMATORS_ORDERED
    if section == SEC_FINAL_UPLOADS:
        return SUB_OPTIONS + _FINAL_UPLOAD_EXTRAS
    if section in (SEC_INITIAL_UPLOADS, SEC_DAILY_UPLOADS):
        return SUB_OPTIONS + _INITIAL_DAILY_EXTRAS
    if section in SUB_SECTIONS:
        return SUB_OPTIONS
    return None


# _status_options_for_section now lives in apa_logic (shim above).


# ── Franchise tag helpers ───────────────────────────────────────────────────
# Local-only labels — never written to the .docx. The key is the bare
# client name (lowercase, whitespace-collapsed, with parentheticals and
# any " - Carrier" / " - Sub" suffixes dropped) so reloads find the tag
# even when the user toggles between "Smith, Jane" / "Smith, Jane - AAA"
# / "Smith, Jane (Contents) - AAA" spellings of the same job.
#
# Without this, a tagged job filed once as "Smith, Jane - AAA" stops
# matching after the user adds a "- Wildfire" suffix or a "(Contents)"
# parenthetical — which is the symptom of "franchise keeps getting lost."
# _FRANCHISE_PAREN_RE + _franchise_key now live in apa_logic (shim above).


# Stable color palette assigned by hashing the franchise name. Keeps the
# same franchise looking the same across reboots without any config.
_FRANCHISE_PALETTE = [
    ("#E0F0FF", "#1F5A8A"),  # blue
    ("#E5F6E5", "#2C6B2F"),  # green
    ("#FFF2D6", "#8A5A1F"),  # amber
    ("#F3E5FF", "#5A2D8A"),  # purple
    ("#FFE0E5", "#8A2D40"),  # rose
    ("#E0F2F2", "#1F6E6E"),  # teal
    ("#FBE7C9", "#8A521F"),  # caramel
    ("#E5E5FF", "#3D3D8A"),  # indigo
]


def _franchise_colors(name):
    if not name:
        return ("#F0F0F0", "#888888")
    idx = sum(ord(c) for c in name) % len(_FRANCHISE_PALETTE)
    return _FRANCHISE_PALETTE[idx]

# WEEKDAY_SPELLING now lives in apa_logic (shim above).


# ── Draft autosave path ────────────────────────────────────────────────────
# Drafts go to %APPDATA%\Linguar Hub\apa_drafts\ — one per doc-date so a
# crash mid-edit doesn't lose work. Recovery on next open compares draft
# mtime vs the .docx mtime.
def _draft_path_for(doc_path):
    base = paths.data("apa_drafts")
    os.makedirs(base, exist_ok=True)
    stem = os.path.splitext(os.path.basename(doc_path))[0]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem)
    return os.path.join(base, f"{safe}.json")


# doc_path_for_today now lives in apa_logic (shim above).


# open_teams_chat + estimator_first_name now live in apa_logic (shim above).
# strip_status_from_text now lives in apa_logic (shim above).


def gather_known_clients(today, days_back=30):
    """Scan the past N days of APA docs to build an autocomplete list of
    'Client Name - Carrier' strings. Returns a sorted list."""
    seen = set()
    for back in range(0, days_back + 1):
        d = today - timedelta(days=back)
        path = doc_path_for_today(d)
        if not os.path.isfile(path):
            continue
        try:
            parsed = parse_existing_doc(path)
        except Exception as ex:
            try:
                import ems_log
                ems_log.warn("apa_monitor",
                    f"skipping unreadable APA doc {path!r}: {ex}")
            except Exception:
                pass
            continue
        for items in parsed.values():
            for text, _ in items:
                base = _strip_to_base(text)
                if 4 < len(base) < 80:
                    seen.add(base)
    return sorted(seen, key=str.lower)


# parse_existing_doc + write_doc now live in apa_logic (shim above). They take
# an optional section_order that defaults to the persisted order — identical
# to reading the old module-global SECTION_ORDER, so callers are unchanged.


def _strip_to_base(text):
    """Reduce 'Last, First - Carrier-Initial-pending(User)' down to
    'Last, First - Carrier' so dedupe matches across sub/status variants.
    Iterates because items may carry both a -sub and a -status trailing."""
    base = re.sub(r'\s*-\s*\d+d\s+inactive.*$', '', (text or "").strip())
    while True:
        before = base
        for trailing in _ALL_TRAILINGS:
            if base.lower().endswith(trailing.lower()):
                base = base[:-len(trailing)].rstrip(" -—")
                break
        if base == before:
            return base


def push_initial_uploads(items, *, status="pending", sub="Initial", today=None):
    """Append rows to today's APA Initial Uploads section without launching
    the GUI. Used by Run Audit's "Push to APA" action.

    Args:
        items: iterable of (client, carrier) pairs. carrier may be None/"".
        status: status from STATUS_OPTIONS (default "pending"). "pending" is
                rendered as "pending(User)" since Initial Uploads is not an
                estimator section.
        sub: sub-category from SUB_OPTIONS (default "Initial").
        today: datetime for which APA doc to update (default now).

    Returns (added, skipped) — lists of "Client - Carrier" base strings.
    Skips clients already present anywhere in today's doc (any section)
    so we don't double-push if they're already tracked.

    If today's doc is missing, carries forward active items from the most
    recent prior doc (mirrors APAMonitorApp's first-open behavior) before
    appending, so the team's running list is preserved.
    """
    today = today or datetime.today()
    doc_path = doc_path_for_today(today)

    if os.path.isfile(doc_path):
        parsed = parse_existing_doc(doc_path)
    else:
        parsed = {s: [] for s in SECTION_ORDER}
        ACTIVE_STATUSES = {"pending", "pending upload", "extended", "uploading"}
        for days_back in range(1, 15):
            d = today - timedelta(days=days_back)
            prior = doc_path_for_today(d)
            if not os.path.isfile(prior):
                continue
            prior_parsed = parse_existing_doc(prior)
            for sec, sec_items in prior_parsed.items():
                for txt, hl in sec_items:
                    low = txt.lower()
                    if hl or any(s in low for s in ACTIVE_STATUSES):
                        parsed.setdefault(sec, []).append((txt, hl))
            break

    existing_keys = set()
    for sec_items in parsed.values():
        for txt, _ in sec_items:
            base = _strip_to_base(txt)
            if base:
                existing_keys.add(base.lower())

    highlight = status.lower() in HIGHLIGHT_STATUSES
    # Initial Uploads is not an estimator section, so plain "pending"
    # round-trips as "pending(User)" — match the GUI's _format_item.
    rendered_status = "pending(User)" if status == "pending" else status

    added, skipped = [], []
    for client, carrier in items:
        client = (client or "").strip()
        if not client:
            continue
        carrier = (carrier or "").strip()
        base = f"{client} - {carrier}" if carrier else client
        key = base.lower()
        if key in existing_keys:
            skipped.append(base)
            continue
        parts = [base]
        if sub:
            parts.append(sub)
        if rendered_status:
            parts.append(rendered_status)
        full = "-".join(parts)
        parsed.setdefault(SEC_INITIAL_UPLOADS, []).append((full, highlight))
        existing_keys.add(key)
        added.append(base)

    if added:
        os.makedirs(os.path.dirname(doc_path), exist_ok=True)
        write_doc(doc_path, today, parsed)
    return added, skipped


# ── GUI ──────────────────────────────────────────────────────────────────────

class APAMonitorApp(ToolPanel):
    TOOL_TITLE        = "APA Monitor"
    TOOL_AUMID        = "Servpro.EMS.APAMonitor"
    TOOL_GEOMETRY_KEY = "apa_monitor"
    DEFAULT_GEOMETRY  = "780x780"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("APA Monitor")
        # Restore last standalone window size/position (no-op when embedded)
        self.restore_geometry()
        self.minsize(620, 500)
        self.configure(bg=BG)
        if os.path.isfile(_ICON):
            try:
                # default=_ICON also fixes the taskbar icon on Windows,
                # not just the window title icon
                self.iconbitmap(default=_ICON)
                self.iconbitmap(_ICON)
            except Exception:
                pass

        self.today = datetime.today()
        self.doc_path = doc_path_for_today(self.today)

        # One-shot migration: collapse legacy franchise-tag keys that used
        # the looser whitespace-only normalization. Self-guards via a
        # version flag, so this is a no-op after the first run.
        try:
            persistence.migrate_franchise_keys(_franchise_key)
        except Exception:
            pass

        # In-memory state: flat {section_name: [item_dict, ...]}
        self.sections = {s: [] for s in SECTION_ORDER}
        self._collapsed = set()
        # Estimator sections hidden unless (a) they have ≥1 card OR
        # (b) the user has toggled them visible via the chip strip
        # below the franchise filter. Persisted per-user so re-opens
        # remember the override set.
        try:
            _vis = persistence.get("apa_visible_estimators") or []
            self._forced_visible_estimators = set(
                str(x).upper() for x in _vis if x)
        except Exception:
            self._forced_visible_estimators = set()
        self._dirty = False
        self._last_saved_at = None
        self._loaded_mtime = None
        # Per-section widget refs so add/delete don't have to rebuild the
        # whole tree (which used to lose scroll position and flash the UI)
        self._section_widgets = {}   # {section_name: {"body":..., "count_lbl":..., "items": list}}
        # Persisted franchise filter — '' means "All", anything else only
        # renders items whose franchise tag matches.
        self._franchise_filter = persistence.get_apa_franchise_filter()
        self._franchise_filter_var = None  # set in _build_ui
        # Draft autosave state
        self._autosave_after_id = None
        self._draft_path = _draft_path_for(self.doc_path)

        # Load today's doc; if missing, carry forward active items from the
        # most recent prior doc so we don't start from blank every day.
        if os.path.isfile(self.doc_path):
            self._load_from_doc()
            try:
                self._loaded_mtime = os.path.getmtime(self.doc_path)
            except OSError:
                pass
        else:
            self._carry_forward_from_prior_day()
            # Auto-write the new day's .docx immediately — without this
            # step the file only appears on the share after the user
            # hits Save, so opening APA at 7am with nothing else queued
            # leaves coworkers seeing yesterday's file as the latest.
            # Writing the carried-forward items right away makes the
            # new day's doc visible to the team from the moment the
            # user starts the app.
            try:
                os.makedirs(os.path.dirname(self.doc_path), exist_ok=True)
                # Same flattener Save uses — converts the in-memory
                # dict items to (text, highlight) tuples that write_doc
                # expects. Skipping this step crashes write_doc with
                # "dict has no attribute strip".
                write_doc(self.doc_path, self.today,
                          self._flatten_sections_for_write())
                self._loaded_mtime = os.path.getmtime(self.doc_path)
            except OSError as ex:
                # Most common cause is the network share being offline;
                # don't crash the launcher — the user can still work
                # locally and Save will retry.
                try:
                    import ems_log
                    ems_log.warn("apa_monitor",
                                 f"auto-create new day doc failed: {ex}")
                except Exception:
                    pass

        # Crash-recovery: if a draft is newer than the loaded .docx (or no
        # .docx exists yet), prompt to restore unsaved edits from last session.
        self._maybe_offer_draft_recovery()

        # Build autocomplete list from recent APA docs
        try:
            self._known_clients = gather_known_clients(self.today, days_back=30)
        except Exception:
            self._known_clients = []

        self._build_ui()
        self._render_all()

        # Ask before closing when there are unsaved edits
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Keyboard shortcuts — Ctrl+S saves, Ctrl+W close-with-prompt
        self.bind_all("<Control-s>", lambda e: self._save())
        self.bind_all("<Control-S>", lambda e: self._save())
        self.bind_all("<Control-w>", lambda e: self._on_close())
        self.bind_all("<Control-W>", lambda e: self._on_close())

        # Date-rollover guard. self.today/self.doc_path are captured at
        # __init__ — without this loop, an app left running across
        # midnight keeps writing to YESTERDAY's path and silently
        # clobbers it. The check fires once a minute and prompts the
        # user before swapping to the new day's doc.
        self._rollover_prompt_open = False
        self.after(60_000, self._check_date_rollover)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self.title(self._title_text(dirty=True))
        # Schedule autosave; multiple edits coalesce into one draft write.
        self._schedule_autosave()

    def _clear_dirty(self):
        self._dirty = False
        self.title(self._title_text(dirty=False))

    # ── Draft autosave ──────────────────────────────────────────────────────
    def _schedule_autosave(self, delay_ms=30_000):
        """Coalesce multiple edits into one draft write 30s after the last
        change. Runs on the main thread but the JSON dump is tiny (<10ms
        for a typical APA day), so no need for a background thread."""
        if self._autosave_after_id is not None:
            try:
                self.after_cancel(self._autosave_after_id)
            except (tk.TclError, ValueError):
                pass
        self._autosave_after_id = self.after(delay_ms, self._write_draft)

    def _write_draft(self):
        self._autosave_after_id = None
        if not self._dirty:
            return
        # Strip widget-only fields that don't need persisting
        to_save = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "doc_path": self.doc_path,
            "sections": {k: list(v) for k, v in self.sections.items()},
            "collapsed": list(self._collapsed),
        }
        try:
            tmp = self._draft_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(to_save, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._draft_path)
        except OSError:
            pass

    def _clear_draft(self):
        try:
            if os.path.isfile(self._draft_path):
                os.remove(self._draft_path)
        except OSError:
            pass

    def _maybe_offer_draft_recovery(self):
        """If a draft for today's doc exists AND it's newer than the .docx
        on disk (or there is no .docx yet), prompt to restore. Only runs
        once at startup."""
        if not os.path.isfile(self._draft_path):
            return
        try:
            draft_mt = os.path.getmtime(self._draft_path)
        except OSError:
            return
        doc_mt = self._loaded_mtime or 0
        if draft_mt <= doc_mt:
            # Draft is older than the saved doc — assume superseded and remove
            self._clear_draft()
            return
        try:
            with open(self._draft_path, encoding="utf-8") as f:
                draft = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._clear_draft()
            return
        when = draft.get("saved_at", "?")
        n_items = sum(len(v) for v in draft.get("sections", {}).values())
        ans = messagebox.askyesno(
            "Restore unsaved APA work?",
            f"Found an unsaved APA draft from {when}\n"
            f"with {n_items} item(s) that wasn't saved to the .docx.\n\n"
            "Restore it now? (Choose No to keep the .docx version and "
            "discard the draft.)",
            parent=self)
        if not ans:
            self._clear_draft()
            return
        # Apply draft over current sections — only known section keys
        for sec, items in draft.get("sections", {}).items():
            if sec in self.sections and isinstance(items, list):
                self.sections[sec] = items
        self._collapsed = set(draft.get("collapsed", []))
        self._dirty = True
        self.title(self._title_text(dirty=True))

    def _title_text(self, dirty=False):
        marker = " •" if dirty else ""
        return f"APA Monitor — {self.today.strftime('%m/%d/%y')}{marker}"

    # ── Date rollover ───────────────────────────────────────────────────────
    def _check_date_rollover(self):
        """Prompt to switch docs when the calendar day has passed since
        __init__. Without this, the app keeps writing to yesterday's
        .docx and clobbers it on the next Save."""
        try:
            now = datetime.today()
            if now.date() != self.today.date():
                self._handle_rollover(now)
        finally:
            # Re-arm regardless so a "No" response gets re-asked next
            # tick — better than the user silently saving over the
            # wrong doc all afternoon.
            try:
                self.after(60_000, self._check_date_rollover)
            except tk.TclError:
                pass  # Window was destroyed.

    def _handle_rollover(self, now):
        # Avoid stacking dialogs if the user is slow to dismiss this.
        if self._rollover_prompt_open:
            return
        self._rollover_prompt_open = True
        try:
            old_label = self.today.strftime("%a %m/%d")
            new_label = now.strftime("%a %m/%d")
            ok = messagebox.askyesno(
                "New day",
                f"It's now {new_label}, but APA Monitor is loaded on "
                f"{old_label}'s doc.\n\n"
                f"Switch to today's doc? Unsaved edits to {old_label} "
                f"will be discarded — saved edits to {old_label}.docx "
                f"are left untouched.",
                parent=self,
            )
            if not ok:
                return
            # Reset state and rebuild as if we just opened on the new day.
            self.today        = now
            self.doc_path     = doc_path_for_today(now)
            self._draft_path  = _draft_path_for(self.doc_path)
            self.sections     = {s: [] for s in SECTION_ORDER}
            self._dirty        = False
            self._loaded_mtime = None
            if os.path.isfile(self.doc_path):
                self._load_from_doc()
                try:
                    self._loaded_mtime = os.path.getmtime(self.doc_path)
                except OSError:
                    pass
            else:
                self._carry_forward_from_prior_day()
                try:
                    os.makedirs(os.path.dirname(self.doc_path), exist_ok=True)
                    write_doc(self.doc_path, self.today,
                              self._flatten_sections_for_write())
                    self._loaded_mtime = os.path.getmtime(self.doc_path)
                except OSError as ex:
                    try:
                        import ems_log
                        ems_log.warn("apa_monitor",
                                     f"rollover doc create failed: {ex}")
                    except Exception:
                        pass
            self.title(self._title_text(dirty=False))
            if hasattr(self, "_path_label"):
                try:
                    self._path_label.configure(text=self.doc_path)
                except tk.TclError:
                    pass
            try:
                self._known_clients = gather_known_clients(
                    self.today, days_back=30)
            except Exception:
                pass
            self._render_all()
        finally:
            self._rollover_prompt_open = False

    def _on_close(self):
        if self._dirty and not self.confirm_save_before(
                "You have unsaved changes. Save before closing?",
                self._save):
            return  # Cancel — stay open
        # Save window geometry so we reopen at the same size/position.
        # No-op when embedded (where self.geometry() would return the
        # launcher's geometry, not ours).
        self.save_geometry()
        self.destroy()

    def on_hide(self):
        """Called by the launcher when the user navigates to another tool.
        Returns False if the user cancels navigation (unsaved changes path)."""
        if not self._dirty:
            return True
        return self.confirm_save_before(
            "You have unsaved APA Monitor changes. Save before switching tools?",
            self._save)

    def _carry_forward_from_prior_day(self):
        """Pull still-active items from the most recent earlier APA doc."""
        ACTIVE_STATUSES = {"pending", "pending upload", "extended", "uploading"}
        for days_back in range(1, 15):
            d = self.today - timedelta(days=days_back)
            path = doc_path_for_today(d)
            if not os.path.isfile(path):
                continue
            parsed = parse_existing_doc(path)
            for section, items in parsed.items():
                for text, highlighted in items:
                    wrapped = self._wrap_item(text, highlighted)
                    status  = wrapped.get("status", "").lower()
                    if highlighted or status in ACTIVE_STATUSES:
                        self.sections[section].append(wrapped)
            return  # stop at first prior doc we find

    # ── Load / save ─────────────────────────────────────────────────────────
    def _load_from_doc(self):
        parsed = parse_existing_doc(self.doc_path)
        for s, items in parsed.items():
            self.sections[s] = [self._wrap_item(*e) for e in items]
        # First-seen sync to the Dispute Tracker workbook: every row in
        # the Audit Dispute section that isn't already in the tracker
        # gets a row created with Intake Source = XA. Insert-if-missing
        # semantics — re-loads don't overwrite the user's edits to the
        # tracker. Run on a background thread so the (synchronous)
        # xlsx open + per-item dedup check doesn't block APA Monitor's
        # init path — that path runs on the main thread during the
        # launcher's _preload_panels sweep, so a slow workbook would
        # delay every other panel after APA in the preload queue.
        try:
            import threading as _th
            _th.Thread(target=self._sync_audit_disputes_to_tracker,
                        daemon=True).start()
        except Exception:
            # Tracker sync is a best-effort side effect; never let it
            # break the APA panel's load path.
            pass

    def _sync_audit_disputes_to_tracker(self) -> int:
        """Push every Audit Dispute item to dispute_tracker as a
        first-seen insert. Returns the count of new rows created (0 if
        all items were already in the tracker). Errors per-row are
        swallowed so one bad item doesn't block the rest.

        Batched-read implementation: the prior version called
        `_exists_for(...)` per item, which re-read the entire workbook
        N times → O(N²) cost. Now we snapshot the existing dedup-keys
        once via a single `read_rows()` call, then check each item
        against the in-memory set."""
        try:
            import dispute_tracker as _dt
        except Exception:
            return 0
        items = self.sections.get(SEC_AUDIT_DISPUTE) or []
        if not items:
            return 0
        # Snapshot existing keys in ONE workbook read instead of one
        # per item. Falls back to an empty set on failure (we'll
        # treat every item as new — upsert dedups on its own writeside).
        try:
            existing_keys = {
                _dt._canon_key(r.get(_dt.COL_CLAIM),
                                r.get(_dt.COL_INSURED))
                for r in _dt.read_rows()
            }
            existing_keys.discard("")
        except Exception:
            existing_keys = set()
        created = 0
        for it in items:
            text = (it.get("text") or "").strip()
            if not text:
                continue
            # APA item text is typically 'Lastname, Firstname - Carrier'
            # — peel the carrier off the trailing ' - <Carrier>' chunk
            # if there is one. Anything left is the insured.
            insured = text
            carrier = ""
            if " - " in text:
                left, _, right = text.rpartition(" - ")
                if left.strip() and right.strip():
                    insured = left.strip()
                    carrier = right.strip()
            # Cheap in-memory existence check — skip work entirely
            # when this item is already tracked.
            try:
                key = _dt._canon_key("", insured)
            except Exception:
                key = ""
            if key and key in existing_keys:
                continue
            # Build a one-line summary describing what surfaced.
            sub = (it.get("sub") or "").strip()
            status = (it.get("status") or "").strip()
            summary_bits = ["Auto-imported from APA Monitor (Audit Dispute)"]
            if sub:
                summary_bits.append(f"sub={sub}")
            if status:
                summary_bits.append(f"status={status}")
            summary = " · ".join(summary_bits)
            try:
                was_new, _row = _dt.upsert_from_apa(
                    insured=insured, claim="", carrier=carrier,
                    summary=summary)
                if was_new:
                    created += 1
                    if key:
                        existing_keys.add(key)
            except Exception:
                continue
        return created

    def _wrap_item(self, text, highlighted=False):
        """Split text like 'Brew, Brian - AAA-Testing/Clearance-extended' into
        {text: 'Brew, Brian - AAA', sub: 'Testing/Clearance', status: 'extended'}.
        Longest known option wins so compound values aren't mis-parsed."""
        item = {"text": text, "sub": "", "status": "", "franchise": ""}
        remaining = text.strip()

        # Peel status from the end (longest match first across all variants)
        for s in sorted(_ALL_STATUS_VARIANTS, key=len, reverse=True):
            if remaining.lower().rstrip(".").endswith(s.lower()):
                idx = remaining.lower().rfind(s.lower())
                remaining = remaining[:idx].rstrip(" -—")
                if s.lower() == "pending upload":
                    item["status"] = "pending upload"
                elif s.lower() == "uploading":
                    # Legacy tag → universal "pending upload" (highlights).
                    item["status"] = "pending upload"
                elif s.lower().startswith("pending"):
                    item["status"] = "pending"
                else:
                    item["status"] = s
                break

        # Peel sub-category from the end (SUB_OPTIONS + estimator names)
        sub_candidates = [x for x in SUB_OPTIONS if x] + ESTIMATORS_ORDERED
        for s in sorted(sub_candidates, key=len, reverse=True):
            if remaining.lower().rstrip(".").endswith(s.lower()):
                idx = remaining.lower().rfind(s.lower())
                remaining = remaining[:idx].rstrip(" -—")
                item["sub"] = s
                break

        item["text"] = remaining
        # Apply persisted franchise tag (UI-only, never written to .docx)
        try:
            tags = persistence.get_franchise_tags()
            item["franchise"] = tags.get(_franchise_key(remaining), "")
        except Exception:
            item["franchise"] = ""
        return item

    def _format_item(self, item, in_estimator=False):
        """Assemble 'text-sub-status', skipping empty fields.
        If status is 'pending' and the item is NOT in an estimator section,
        write it as 'pending(User)' to mark that the user owns the follow-up."""
        parts = []
        if item.get("text", "").strip():
            parts.append(item["text"].strip())
        if item.get("sub"):
            parts.append(item["sub"])
        status = item.get("status", "")
        if status == "pending" and not in_estimator:
            status = "pending(User)"
        if status:
            parts.append(status)
        return "-".join(parts)

    def _flatten_sections_for_write(self):
        """Convert in-memory section dicts to the (text, highlight)-tuple
        layout `write_doc` expects. Shared between _save and the
        startup auto-create so both go through the same formatter.

        Iterates SECTION_ORDER (not self.sections) so a section added
        later in SECTION_ORDER but not present in the in-memory dict
        — e.g., an old loaded doc that pre-dates a new section — still
        round-trips with an empty body instead of disappearing."""
        def _pack(items, in_estimator):
            out = []
            for i in items:
                if i["text"].strip() or i["status"] or i.get("sub"):
                    highlight = i.get("status", "").lower() in HIGHLIGHT_STATUSES
                    out.append((self._format_item(i, in_estimator=in_estimator),
                                highlight))
            return out
        return {s: _pack(self.sections.get(s, []), s in ESTIMATOR_SECTIONS)
                for s in SECTION_ORDER}

    def _save(self):
        # Concurrent-edit guard: warn if file changed on disk since we loaded
        if (self._loaded_mtime and os.path.isfile(self.doc_path)
                and os.path.getmtime(self.doc_path) > self._loaded_mtime + 1):
            answer = messagebox.askyesno(
                "File changed externally",
                "This APA doc was modified outside of APA Monitor since you "
                "loaded it (Word may have it open).\n\n"
                "Save anyway and overwrite those changes?",
                parent=self)
            if not answer:
                return

        flat = self._flatten_sections_for_write()

        # Keep a single rolling backup so a bad save is recoverable.
        # Stored under %APPDATA%\Linguar Hub\apa_backups\ — private to the
        # user, NOT in X:\IE_Public\ where coworkers would see it.
        if os.path.isfile(self.doc_path):
            try:
                import shutil
                bak_dir = paths.data("apa_backups")
                os.makedirs(bak_dir, exist_ok=True)
                bak_path = os.path.join(bak_dir,
                                        os.path.basename(self.doc_path) + ".bak")
                shutil.copy2(self.doc_path, bak_path)
            except OSError:
                pass

        # Re-key franchise tags to match the text actually being saved.
        # The badge stores the franchise on the in-memory item, but the
        # persistence is keyed by client text — if the user edited the
        # text after picking a franchise, the saved key is stale and
        # the next load wouldn't find it. Walking every tagged item now
        # keeps persistence in sync with what's about to hit disk.
        try:
            for items in self.sections.values():
                for it in items:
                    fr = (it.get("franchise") or "").strip()
                    txt = (it.get("text") or "").strip()
                    if fr and txt:
                        persistence.set_franchise_tag(
                            _franchise_key(txt), fr)
        except Exception:
            pass

        # Atomic write: build the docx in a sibling tmp file, double-
        # check mtime once more, then os.replace into place. Without
        # this, two saves landing within ~50ms of each other (user A
        # hits save, user B hits save while A is still mid-render) can
        # both pass the initial concurrent-edit check and still clobber
        # each other — write_doc.save() is NOT atomic. The tmp-then-
        # replace pattern guarantees the target file either holds the
        # full prior version or the full new version, never a mix.
        # Pid in the suffix avoids collision when two APA Monitor
        # instances on different machines save simultaneously to the
        # same SharePoint-synced folder.
        tmp_path = f"{self.doc_path}.{os.getpid()}.saving"
        try:
            write_doc(tmp_path, self.today, flat)
            # Final mtime check — narrows the race to just the os.replace
            # call itself. Anything that landed while we were generating
            # the docx is caught here.
            if (self._loaded_mtime and os.path.isfile(self.doc_path)
                    and os.path.getmtime(self.doc_path) > self._loaded_mtime + 1):
                ans = messagebox.askyesno(
                    "File changed during save",
                    "Another edit landed on this APA doc while you "
                    "were saving. Overwrite it anyway?",
                    parent=self)
                if not ans:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    return
            os.replace(tmp_path, self.doc_path)
        except Exception as ex:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            try:
                import ems_log
                ems_log.error("apa_monitor", f"Save failed: {ex}")
            except Exception:
                pass
            messagebox.showerror("Save failed", str(ex), parent=self)
            return
        self._clear_dirty()
        self._last_saved_at = datetime.today()
        try:
            self._loaded_mtime = os.path.getmtime(self.doc_path)
        except OSError:
            pass
        # Saved state matches disk now — drop the draft so we don't offer
        # to restore it next launch.
        self._clear_draft()
        self._update_saved_label()

    def _tick_saved_label(self):
        self._update_saved_label()
        # Re-tick every 30 seconds so "X min ago" stays current
        self.after(30_000, self._tick_saved_label)

    def _update_saved_label(self):
        if not hasattr(self, "_saved_label"):
            return
        if not self._last_saved_at:
            self._saved_label.configure(text="not saved yet", text_color=TEXT_GRAY)
            return
        delta = datetime.today() - self._last_saved_at
        secs  = int(delta.total_seconds())
        if secs < 60:
            label = "saved just now"
        elif secs < 3600:
            label = f"saved {secs // 60} min ago"
        elif secs < 86400:
            label = f"saved {secs // 3600}h ago"
        else:
            label = self._last_saved_at.strftime("saved %m/%d %H:%M")
        self._saved_label.configure(text=label, text_color=GREEN_DARK)

    # ── Teams messaging ────────────────────────────────────────────────────
    def _note_for(self, item, section):
        """Pull the persisted Teams-message note for an Audit row, or "" for
        non-audit rows / unsaved entries. Resolves the storage key from the
        row's current text so inline edits stay in sync."""
        if section not in AUDIT_SECTIONS:
            return ""
        base = _strip_to_base(item.get("text", "") or "")
        if not base:
            return ""
        try:
            return persistence.get_apa_message_note(base, section)
        except Exception:
            return ""

    @staticmethod
    def _indent_note(note):
        """Format a saved note as indented body text under a Teams bullet.
        Empty note → empty string (caller can append unconditionally)."""
        if not note:
            return ""
        lines = [ln for ln in note.splitlines() if ln.strip()]
        if not lines:
            return ""
        return "\n  " + "\n  ".join(lines)

    def _send_teams_about_item(self, estimator, item, section=None):
        email = persistence.get_estimator_email(estimator)
        if not email:
            self._prompt_for_email(estimator)
            return
        first  = estimator_first_name(estimator)
        client = strip_status_from_text(item.get("text", ""))
        if section in AUDIT_SECTIONS:
            msg = (f"Hey {first}, can you take a look at this "
                   f"{section.lower()}: {client}?")
            msg += self._indent_note(self._note_for(item, section))
        else:
            msg = f"Hey {first}, will you be uploading this job today: {client}?"
        if not open_teams_chat(email, msg):
            messagebox.showerror("Teams open failed",
                                  "Could not launch Teams. Is the desktop app installed?",
                                  parent=self)

    def _build_combined_message(self, estimator, items_with_sections):
        """One message per estimator listing all their outstanding jobs.
        `items_with_sections` is [(item, section), ...]. Items in
        AUDIT_SECTIONS get their persisted note appended as indented body
        text under their bullet; uploading items keep the legacy phrasing."""
        first = estimator_first_name(estimator)
        if len(items_with_sections) == 1:
            item, sec = items_with_sections[0]
            client = strip_status_from_text(item.get("text", ""))
            if sec in AUDIT_SECTIONS:
                msg = (f"Hey {first}, can you take a look at this "
                       f"{sec.lower()}: {client}?")
                msg += self._indent_note(self._note_for(item, sec))
                return msg
            return f"Hey {first}, will you be uploading this job today: {client}?"

        upload_items = [(i, s) for i, s in items_with_sections
                         if s not in AUDIT_SECTIONS]
        audit_items  = [(i, s) for i, s in items_with_sections
                         if s in AUDIT_SECTIONS]
        parts = [f"Hey {first},"]
        if upload_items:
            parts.append("will you be uploading these jobs today:")
            for i, _ in upload_items:
                parts.append("  • " + strip_status_from_text(i.get("text", "")))
        if audit_items:
            if upload_items:
                parts.append("")
            parts.append("can you also take a look at these audit items:")
            for i, sec in audit_items:
                client = strip_status_from_text(i.get("text", ""))
                label = ("Rejection" if sec == SEC_AUDIT_REJECTION
                         else "Dispute")
                parts.append(f"  • {client}  ({label})")
                note = self._note_for(i, sec)
                if note:
                    for nl in note.splitlines():
                        if nl.strip():
                            parts.append("      " + nl)
        return "\n".join(parts)

    def _outstanding_for(self, estimator):
        """Items in this estimator's own section AND items in Audit
        Rejection / Audit Dispute where this estimator is the selected sub —
        excluding anything already marked 'uploaded'. Returns a list of
        (item, section) tuples so message-builders can attach the right
        verbiage and any per-row note."""
        out = []
        for i in self.sections.get(estimator, []):
            if i["text"].strip() and i.get("status", "").lower() != "uploaded":
                out.append((i, estimator))
        for sec in AUDIT_SECTIONS:
            for i in self.sections.get(sec, []):
                if (i.get("sub", "").strip().upper() == estimator.upper()
                        and i["text"].strip()
                        and i.get("status", "").lower() != "uploaded"):
                    out.append((i, sec))
        return out

    def _send_teams_to_estimator(self, estimator):
        """Open ONE Teams chat for this estimator with all their jobs combined."""
        email = persistence.get_estimator_email(estimator)
        if not email:
            self._prompt_for_email(estimator)
            return
        active = self._outstanding_for(estimator)
        if not active:
            messagebox.showinfo("Nothing to ask",
                                f"No outstanding items for {estimator.title()}.",
                                parent=self)
            return
        msg = self._build_combined_message(estimator, active)
        if not open_teams_chat(email, msg):
            messagebox.showerror("Teams open failed",
                "Could not launch Teams. Is the desktop app installed?",
                parent=self)

    def _send_teams_for_audit_section(self, section):
        """For an audit section (Audit Rejection/Audit Dispute), group items
        by the sub-estimator and open one Teams chat per estimator with their
        outstanding items from that section."""
        by_est = {}
        for it in self.sections.get(section, []):
            sub = it.get("sub", "").strip()
            if not sub or not it.get("text", "").strip():
                continue
            if it.get("status", "").lower() == "uploaded":
                continue
            by_est.setdefault(sub.upper(), []).append(it)

        if not by_est:
            messagebox.showinfo("Nothing to send",
                                f"No estimators are tagged on {section} items.",
                                parent=self)
            return

        targets = []          # [(estimator, email, [items])]
        missing_email = []
        for est, items in by_est.items():
            email = persistence.get_estimator_email(est)
            if email:
                targets.append((est, email, items))
            else:
                missing_email.append(est)

        if missing_email:
            names = ", ".join(estimator_first_name(e) for e in missing_email)
            if not messagebox.askyesno(
                    "Some estimators have no email",
                    f"Skipping (no email saved): {names}\n\n"
                    "Set them up via 'Estimator Contacts'.\n\n"
                    f"Continue with the {len(targets)} estimator(s) that have email?",
                    parent=self):
                return

        if not targets:
            return

        if not messagebox.askyesno(
                f"Send {section} items",
                f"This will open {len(targets)} Teams chat(s) — one per "
                f"estimator tagged in {section}.\n\nContinue?",
                parent=self):
            return

        for idx, (est, email, items) in enumerate(targets, 1):
            first = estimator_first_name(est)
            if len(items) == 1:
                it = items[0]
                client = strip_status_from_text(it.get("text", ""))
                msg = (f"Hey {first}, can you take a look at this "
                       f"{section.lower()}: {client}?")
                msg += self._indent_note(self._note_for(it, section))
            else:
                parts = [f"Hey {first}, can you take a look at these "
                          f"{section.lower()} items:"]
                for it in items:
                    parts.append("  • " + strip_status_from_text(it.get("text", "")))
                    note = self._note_for(it, section)
                    if note:
                        for nl in note.splitlines():
                            if nl.strip():
                                parts.append("      " + nl)
                msg = "\n".join(parts)
            if not open_teams_chat(email, msg):
                messagebox.showerror("Teams open failed",
                    "Could not launch Teams. Is the desktop app installed?",
                    parent=self)
                return
            if idx < len(targets):
                next_first = estimator_first_name(targets[idx][0])
                if not messagebox.askyesno(
                        f"Sent to {first} ({idx}/{len(targets)})",
                        f"Opened Teams chat with {first}.\n\n"
                        f"Continue to {next_first} ({len(targets) - idx} remaining)?",
                        parent=self):
                    break

    def _send_teams_to_all(self):
        """Open one Teams chat per estimator that has outstanding jobs.
        Each estimator gets ONE combined message about all their jobs,
        including any items in the Audit Rejection / Audit Dispute sections
        where that estimator is set as the Sub.

        Sweeps ESTIMATORS_ORDERED first, then adds any subs from the audit
        sections that aren't already in that list so nothing slips through."""
        # Collect any sub values in audit sections that aren't in the
        # standard estimator list, preserving first-seen order.
        covered = {e.upper() for e in ESTIMATORS_ORDERED}
        extra_subs = []
        for sec in AUDIT_SECTIONS:
            for it in self.sections.get(sec, []):
                sub = it.get("sub", "").strip()
                if (sub and sub.upper() not in covered
                        and it.get("text", "").strip()
                        and it.get("status", "").lower() != "uploaded"):
                    extra_subs.append(sub)
                    covered.add(sub.upper())

        all_ests = list(ESTIMATORS_ORDERED) + extra_subs

        targets = []   # [(estimator, email, [items])]
        missing_email = []
        for est in all_ests:
            active = self._outstanding_for(est)
            if not active:
                continue
            email = persistence.get_estimator_email(est)
            if email:
                targets.append((est, email, active))
            else:
                missing_email.append(est)

        # Detect audit-section items whose sub wasn't resolved to any target
        # (sub is blank, or set to a value that has no email saved and isn't
        # in ESTIMATORS_ORDERED at all). Warn up-front so they can't silently
        # vanish from the send sweep.
        _resolved_upper = {e.upper() for e, _, _ in targets} | {
            e.upper() for e in missing_email}
        _unresolved = []
        for _sec in AUDIT_SECTIONS:
            for _it in self.sections.get(_sec, []):
                _sub = _it.get("sub", "").strip()
                _txt = _it.get("text", "").strip()
                if (not _sub and _txt
                        and _it.get("status", "").lower() != "uploaded"):
                    _unresolved.append(f"  • {_txt}  [{_sec}] — no estimator set")
                elif (_sub and _txt
                        and _sub.upper() not in _resolved_upper
                        and _it.get("status", "").lower() != "uploaded"):
                    _unresolved.append(
                        f"  • {_txt}  [{_sec}] — '{_sub}' has no email saved")
        if _unresolved:
            messagebox.showwarning(
                "Some rejection/dispute items will be skipped",
                "These items won't be sent — fix the Sub or add an email:\n\n"
                + "\n".join(_unresolved[:10]),
                parent=self)

        if not targets and not missing_email:
            messagebox.showinfo("Nothing to send",
                                "No estimators have outstanding jobs.",
                                parent=self)
            return

        if missing_email:
            names = ", ".join(estimator_first_name(e) for e in missing_email)
            if not messagebox.askyesno(
                    "Some estimators have no email",
                    f"Skipping (no email saved): {names}\n\n"
                    "Set them up via 'Estimator Contacts'.\n\n"
                    f"Continue with the {len(targets)} estimator(s) that have email?",
                    parent=self):
                return

        if not messagebox.askyesno(
                "Send to all estimators",
                f"This will open {len(targets)} separate Teams chats — one per "
                "estimator, each pre-filled with their outstanding jobs.\n\n"
                "You'll be asked to confirm between each so you control the pace.\n\n"
                "Continue?", parent=self):
            return

        for idx, (est, email, items) in enumerate(targets, 1):
            try:
                msg = self._build_combined_message(est, items)
            except Exception as _ex:
                messagebox.showerror("Message build failed",
                    f"Couldn't build message for {est}: {_ex}",
                    parent=self)
                continue
            first = estimator_first_name(est)
            remaining_label = (f"  ({len(targets) - idx} more after this)"
                               if idx < len(targets) else "  (last one)")
            # Ask BEFORE opening Teams so the user has time to read the
            # preview. Clicking OK opens the chat; Cancel skips this one.
            if not messagebox.askyesno(
                    f"Open Teams chat — {first}  ({idx}/{len(targets)})",
                    f"Ready to open Teams for {first}?{remaining_label}\n\n"
                    f"Preview:\n{msg[:300]}{'…' if len(msg) > 300 else ''}\n\n"
                    "Click OK to open Teams, then finalize and send the "
                    "message there. Come back here for the next one.",
                    parent=self):
                continue
            if not open_teams_chat(email, msg):
                messagebox.showerror("Teams open failed",
                    "Could not launch Teams. Is the desktop app installed?",
                    parent=self)
                return

    def _prompt_for_email(self, estimator):
        if messagebox.askyesno(
                "No email saved",
                f"No Teams email saved for {estimator.title()}.\n\n"
                "Open the Estimator Contacts dialog to add it now?",
                parent=self):
            self._open_contacts_dialog()

    # ── EOD email ───────────────────────────────────────────────────────────
    def _doc_text_for_email(self):
        """Flatten the loaded sections into the same plain-text shape the
        .docx renders. Mirrors the section/numbered-item layout the daily
        email recipients are used to seeing."""
        lines = []
        for sec in SECTION_ORDER:
            items = self.sections.get(sec, [])
            if not items:
                continue
            lines.append(sec)
            for i, it in enumerate(items, 1):
                # Reuse the same item-line shape as save() writes to .docx
                txt = it.get("text", "").strip()
                sub = it.get("sub", "").strip()
                status = it.get("status", "").strip()
                parts = [f"{i}. {txt}"]
                if sub:
                    parts.append(f"({sub})")
                if status:
                    parts.append(f"-{status}")
                lines.append(" ".join(parts))
            lines.append("")  # blank line between sections
        return "\n".join(lines).rstrip() + "\n"

    def _send_eod_email(self):
        recipients = persistence.get_eod_recipients()
        if not recipients:
            if not messagebox.askyesno(
                    "No recipients yet",
                    "No EOD recipients saved. Add some now?",
                    parent=self):
                return
            self._open_eod_recipients_dialog()
            recipients = persistence.get_eod_recipients()
            if not recipients:
                return

        body = self._doc_text_for_email()
        subject = f"APA EOD - {self.today.strftime('%a %m/%d/%Y')}"

        # Always copy to clipboard so the user can paste into the chained
        # email thread (whether we manage to compose a fresh email or not).
        try:
            self.clipboard_clear()
            self.clipboard_append(body)
            self.update()  # flush so clipboard sticks even if window closes
        except tk.TclError:
            pass

        # Open Outlook Web's compose deeplink in the browser. The
        # previous flow drove the desktop Outlook app via COM, which
        # the user doesn't want — they prefer the web client. The
        # deeplink URL pre-fills TO + Subject + Body just like the
        # COM path did, no Windows Outlook side-effect.
        # Body still goes to the clipboard in case the URL hits a
        # browser/length cap and the body field truncates.
        import urllib.parse
        import webbrowser
        params = {
            "to":      ",".join(recipients),
            "subject": subject,
            "body":    body,
        }
        url = ("https://outlook.office.com/mail/deeplink/compose?"
               + urllib.parse.urlencode(params, quote_via=urllib.parse.quote))
        try:
            webbrowser.open(url, new=2)  # new=2 → new tab if possible
        except Exception:
            notify_error(self, "Email",
                         "Could not open Outlook Web in the browser.")
            return

        show_toast(self, "Body copied to clipboard — paste into the email",
                   kind="success", duration=3000)

    def _open_manage_estimators_dialog(self):
        """Modal to reorder / add / remove APA section rows. Every row
        (including built-in sections like Final Uploads, Initial
        Uploads, Audit Rejection) can be reordered. Estimator rows can
        also be added or removed; built-in rows can only be reordered
        (removing them would break dependent code that keys by section
        name). Persisted to `state["apa_section_order"]`."""
        dlg = tk.Toplevel(self)
        dlg.title("Manage APA sections")
        try:
            # Tall enough that head + 8-row default list + Add row +
            # Save bar all fit without clipping; list scrolls when the
            # roster outgrows this height.
            dlg.geometry("560x680")
            dlg.minsize(480, 520)
        except tk.TclError:
            pass
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        # Header
        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x", side="top")
        tk.Label(head, text="📋 APA section order",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(head,
                 text=("Drag the ⠿ handle to reorder. Estimator rows "
                       "can be added (bottom) or removed (✕). Built-in "
                       "section rows (Final/Initial/Daily Uploads, "
                       "Pending Review, Audit Rejection/Dispute, etc.) "
                       "show 🔒 and can only be reordered."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=520, justify="left", anchor="w"
                 ).pack(fill="x", pady=(4, 0))

        # IMPORTANT: pack the bottom-pinned controls (Save/Cancel +
        # Add row) BEFORE the scrollable list, so when geometry is
        # tight tk doesn't push them off-screen. Tk's pack manager
        # honors widgets packed earlier when allocating space; pinning
        # the bottom controls first guarantees they always show even
        # if the list ends up clipped.
        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(side="bottom", fill="x")
        add_row = tk.Frame(dlg, bg=BG, padx=14, pady=6)
        add_row.pack(side="bottom", fill="x")
        tk.Frame(dlg, bg=BORDER, height=1
                  ).pack(side="bottom", fill="x")

        # Working list — full section order, not just estimators.
        roster = list(SECTION_ORDER)

        # Scrollable so a 20+ estimator roster doesn't blow out the
        # window. ScrollableFrame uses a canvas + inner Frame; we
        # pack list_frame INTO that inner Frame.
        list_scroll = ScrollableFrame(dlg, bg=WHITE, canvas_bg=WHITE,
                                       padx=0, pady=0)
        list_scroll.pack(fill="both", expand=True, padx=14, pady=8)
        list_scroll.configure(highlightthickness=1,
                              highlightbackground=BORDER)
        list_frame = list_scroll.inner

        # Per-row drag-and-drop state — cleared on _drag_end. Stored
        # on a closure cell so the bound handlers can update it.
        drag_state = {"name": None, "row": None, "indicator": None}
        row_widgets: list[tuple[str, tk.Frame]] = []

        def _drop_indicator():
            """Lazy-create the green drop-position bar. Lives in the
            list_frame as a sibling of the rows; we just `place()` it
            at the right Y as the user drags. Re-used across drags
            so we don't churn widget creation on every motion event."""
            ind = drag_state.get("indicator")
            if ind is not None:
                try:
                    if ind.winfo_exists():
                        return ind
                except tk.TclError:
                    pass
            ind = tk.Frame(list_frame, bg=GREEN, height=3,
                            highlightthickness=0)
            drag_state["indicator"] = ind
            return ind

        def _rebuild_list():
            for w in list_frame.winfo_children():
                w.destroy()
            row_widgets.clear()
            for i, name in enumerate(roster):
                is_builtin = name in _BUILTIN_SET
                row = tk.Frame(list_frame, bg=WHITE)
                row.pack(fill="x", padx=4, pady=1)
                row_widgets.append((name, row))

                # ⠿ drag handle — mirrors the pattern the Snapshot
                # tool uses for its sub/log rows. Every row gets one
                # (including built-ins; they're reorderable just not
                # removable, so we want them draggable too).
                handle = tk.Label(
                    row, text="⠿",
                    font=("Segoe UI Variable", 11),
                    bg=WHITE, fg=TEXT_MUTED,
                    cursor="size_ns", padx=6)
                handle.pack(side="left")
                handle.bind(
                    "<ButtonPress-1>",
                    lambda _e, nm=name, rr=row:
                        _drag_start(nm, rr))
                handle.bind("<B1-Motion>", _drag_motion)
                handle.bind("<ButtonRelease-1>", _drag_end)

                # Built-in rows get a subtle gray label + a 🔒 hint so
                # the user understands why ✕ is hidden.
                label_text = (f"{name}  🔒" if is_builtin else name)
                tk.Label(row, text=label_text,
                         font=("Segoe UI Variable", 10,
                               "normal" if is_builtin else "bold"),
                         bg=WHITE,
                         fg=TEXT_GRAY if is_builtin else TEXT_DARK,
                         anchor="w", padx=8).pack(side="left",
                                                     fill="x", expand=True)
                # ✕ only for estimator rows. Built-ins are load-bearing
                # — other code references them by string and would
                # break if they vanished.
                if not is_builtin:
                    icon_button(
                        row, "✕", fg=FLAG_RED, padx=4, pady=4,
                        command=lambda idx=i: _remove(idx),
                        tooltip="Remove",
                    ).pack(side="right", padx=(2, 6))

        def _drag_start(name, row_widget):
            drag_state["name"] = name
            drag_state["row"] = row_widget
            try:
                # Visual cue — slight tint so the user knows which row
                # they grabbed. Reset on _drag_end.
                row_widget.configure(bg=SURFACE_2)
                for child in row_widget.winfo_children():
                    try:
                        child.configure(bg=SURFACE_2)
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass

        def _target_index_at(mouse_y_root):
            """Map a screen Y coord to a 0..len(roster) target index.
            Returns the position where the dragged row would land if
            dropped here — same logic for the live drop indicator and
            the final drop. Index == len(roster) means "drop at end"."""
            target_idx = len(roster)
            for i, (_nm, rw) in enumerate(row_widgets):
                try:
                    top = rw.winfo_rooty()
                    mid = top + rw.winfo_height() // 2
                except tk.TclError:
                    continue
                if mouse_y_root < mid:
                    target_idx = i
                    break
            return target_idx

        def _drag_motion(event):
            """Live drop indicator — a thin green bar that snaps to the
            gap between rows where the dragged row would land. Trello-
            style visual feedback so the user can see the target
            position before committing."""
            if not drag_state.get("name"):
                return
            target_idx = _target_index_at(event.y_root)
            ind = _drop_indicator()
            # Position the indicator relative to list_frame's local
            # coords. Use the boundary above row[target_idx], or
            # below the last row when dropping at the end.
            try:
                if target_idx < len(row_widgets):
                    _nm, rw = row_widgets[target_idx]
                    y_local = (rw.winfo_rooty()
                                - list_frame.winfo_rooty())
                else:
                    # Drop at the very end — bar sits below the last row.
                    _nm, last_rw = row_widgets[-1]
                    y_local = ((last_rw.winfo_rooty()
                                 + last_rw.winfo_height())
                                - list_frame.winfo_rooty())
                ind.place(in_=list_frame, x=0, y=max(0, y_local - 1),
                          relwidth=1.0, height=3)
                ind.lift()
            except tk.TclError:
                pass

        def _drag_end(event):
            name = drag_state.get("name")
            origin_row = drag_state.get("row")
            ind = drag_state.get("indicator")
            drag_state["name"] = None
            drag_state["row"] = None
            # Hide the drop indicator. Keep the widget around so the
            # next drag re-uses it instead of churning a new Frame.
            if ind is not None:
                try:
                    ind.place_forget()
                except tk.TclError:
                    pass
            # Restore the dragged row's bg before reorder triggers a
            # rebuild (which destroys this widget anyway, but the
            # restore prevents a tinted flash on cancelled drops).
            if origin_row is not None:
                try:
                    origin_row.configure(bg=WHITE)
                    for child in origin_row.winfo_children():
                        try:
                            child.configure(bg=WHITE)
                        except tk.TclError:
                            pass
                except tk.TclError:
                    pass
            if not name or name not in roster:
                return
            target_idx = _target_index_at(event.y_root)
            cur_idx = roster.index(name)
            # _target_index_at returns the SLOT to insert at. If the
            # user drops in the same slot OR the slot immediately after
            # the row's current position, that's a no-op (it'd just
            # land back where it started).
            if target_idx == cur_idx or target_idx == cur_idx + 1:
                return
            roster.remove(name)
            # When dropping below the row's old position, removing
            # shifted every later index down by 1 — compensate so the
            # drop lands where the indicator was.
            if target_idx > cur_idx:
                target_idx -= 1
            roster.insert(target_idx, name)
            _rebuild_list()

        def _remove(idx):
            # Guard against removing builtins via stale index — UI hides
            # the button but a clever user could trigger old closures
            # after a reorder. Skip silently in that case.
            name = roster[idx]
            if name in _BUILTIN_SET:
                return
            roster.pop(idx)
            _rebuild_list()

        _rebuild_list()

        # Add row controls — `add_row` Frame is pre-packed at the
        # bottom (above the Save bar). Just pack labels/entry/button
        # into it.
        tk.Label(add_row, text="Add estimator:",
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_DARK
                 ).pack(side="left")
        entry = ttk.Entry(add_row, width=24)
        entry.pack(side="left", padx=(6, 0))

        def _add():
            name = entry.get().strip().upper()
            if not name:
                return
            if name in roster:
                messagebox.showinfo("Already in roster",
                                      f"{name} is already listed.",
                                      parent=dlg)
                return
            # New estimator goes right before the Initial Uploads row
            # (its canonical home in the APA doc). Falls back to end
            # if Initial Uploads has been moved or removed somehow.
            try:
                pos = roster.index(SEC_INITIAL_UPLOADS)
            except ValueError:
                pos = len(roster)
            roster.insert(pos, name)
            entry.delete(0, "end")
            _rebuild_list()
        entry.bind("<Return>", lambda _e: _add())
        done_button(add_row, "+ Add", padx=12, pady=2,
                     command=_add).pack(side="left", padx=(6, 0))

        # Save / Cancel — `bot` Frame is pre-packed at the very
        # bottom; widgets just attach into it.
        def _save_and_close():
            import persistence as _per
            try:
                _per.set_value("apa_section_order", list(roster))
                # Also clear the legacy key so it doesn't shadow the
                # new one on next read.
                try:
                    _per.set_value("apa_estimators", None)
                except Exception:
                    pass
            except Exception as ex:
                messagebox.showerror("Save failed", str(ex), parent=dlg)
                return
            _reload_estimators_cache()
            # Initialize sections dict for any new entries; preserve
            # rows for any that survived the reorder.
            for s in SECTION_ORDER:
                self.sections.setdefault(s, [])
            dlg.destroy()
            try:
                self._render_all()
            except Exception:
                pass
            try:
                show_toast(self,
                           f"Section order saved ({len(roster)} rows)",
                           kind="success")
            except Exception:
                pass

        secondary_button(bot, "Cancel", padx=12, pady=4,
                          command=dlg.destroy
                          ).pack(side="right", padx=(8, 0))
        done_button(bot, "💾 Save", padx=14, pady=4,
                     command=_save_and_close).pack(side="right")

    def _open_eod_recipients_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("EOD Email Recipients")
        dlg.geometry("440x420")
        dlg.configure(bg=BG)
        dlg.grab_set()

        tk.Label(dlg, text="Recipients for the daily APA EOD email",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 padx=10, pady=8).pack(anchor="w")
        tk.Label(dlg, text="One email per line. Saved across sessions.",
                 font=("Segoe UI Variable", 8),
                 bg=BG, fg=TEXT_GRAY,
                 padx=10).pack(anchor="w")

        body = tk.Frame(dlg, bg=BG, padx=10, pady=8)
        body.pack(fill="both", expand=True)
        txt = tk.Text(body, wrap="word", font=("Consolas", 10),
                      bg=WHITE, relief="solid", borderwidth=1)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", "\n".join(persistence.get_eod_recipients()))

        bot = tk.Frame(dlg, bg=BG, padx=10, pady=10)
        bot.pack(fill="x")

        def _save():
            raw = txt.get("1.0", "end-1c")
            emails = [line.strip() for line in raw.splitlines() if line.strip()]
            existing = persistence.get_eod_recipients()
            # Guard against accidental wipe: if there were saved recipients
            # and the textbox is now empty, ask before replacing.
            if existing and not emails:
                if not messagebox.askyesno(
                        "Clear all recipients?",
                        f"This will remove all {len(existing)} saved "
                        "recipient(s). Continue?",
                        parent=dlg):
                    return
            persistence.set_eod_recipients(emails)
            show_toast(self, f"Saved {len(emails)} recipient(s)",
                       kind="success", duration=1800)
            dlg.destroy()

        tk.Button(bot, text="Save", font=("Segoe UI Variable", 10, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=14, pady=4,
                  command=_save).pack(side="right")
        tk.Button(bot, text="Cancel", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                  padx=10, pady=4, command=dlg.destroy
                  ).pack(side="right", padx=(0, 6))

    # ── Estimator Contacts dialog ──────────────────────────────────────────
    def _open_contacts_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Estimator Contacts")
        dlg.geometry("420x500")
        dlg.configure(bg=BG)
        dlg.grab_set()

        tk.Label(dlg,
                 text="Enter each estimator's Teams email (work email).",
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_DARK,
                 padx=10, pady=8).pack(anchor="w")

        body = tk.Frame(dlg, bg=BG, padx=10)
        body.pack(fill="both", expand=True)

        emails = persistence.get_estimator_emails()
        entry_vars = {}
        # Snapshot the prefill so save can detect actual edits and avoid
        # deleting a saved email just because its row stayed blank.
        original = {}
        for est in ESTIMATORS_ORDERED:
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{estimator_first_name(est)}:",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=BG, fg=TEXT_DARK, width=12, anchor="w").pack(side="left")
            prefill = emails.get(est, "")
            v = tk.StringVar(value=prefill)
            ttk.Entry(row, textvariable=v, font=("Segoe UI Variable", 9)
                      ).pack(side="left", fill="x", expand=True)
            entry_vars[est] = v
            original[est] = prefill

        bot = tk.Frame(dlg, bg=BG, padx=10, pady=10)
        bot.pack(fill="x")
        def _save_contacts():
            # Only persist rows whose value actually changed. A blank row
            # that was always blank is a no-op; a row that was cleared
            # explicitly still falls through to the delete branch.
            changed = 0
            for est, v in entry_vars.items():
                new_val = v.get().strip()
                if new_val == (original.get(est) or "").strip():
                    continue
                persistence.set_estimator_email(est, new_val)
                changed += 1
            dlg.destroy()
            if changed:
                show_toast(self, f"Saved {changed} estimator email(s)",
                           kind="success")
            else:
                show_toast(self, "No changes", kind="info")
        tk.Button(bot, text="Save", font=("Segoe UI Variable", 10, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=14, pady=4,
                  command=_save_contacts).pack(side="right")
        tk.Button(bot, text="Cancel", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                  padx=10, pady=4, command=dlg.destroy
                  ).pack(side="right", padx=(0, 6))

    def _open_bulk_paste(self):
        """Dialog to paste a list of items, one per line, into a chosen section."""
        dlg = tk.Toplevel(self)
        dlg.title("Paste Multiple Items")
        dlg.geometry("520x420")
        dlg.configure(bg=BG)
        dlg.grab_set()

        tk.Label(dlg, text="Paste one item per line (e.g. 'Smith, John - AAA - extended')",
                 font=("Segoe UI Variable", 9, "bold"), bg=BG, fg=TEXT_DARK,
                 padx=10, pady=8).pack(anchor="w")

        # Section picker
        srow = tk.Frame(dlg, bg=BG, padx=10)
        srow.pack(fill="x")
        tk.Label(srow, text="Add to:", font=("Segoe UI Variable", 9),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        sec_var = tk.StringVar(value=SEC_FINAL_UPLOADS)
        ttk.Combobox(srow, textvariable=sec_var,
                     values=SECTION_ORDER, state="readonly", width=40
                     ).pack(side="left", padx=6)

        body = tk.Frame(dlg, bg=BG, padx=10, pady=6)
        body.pack(fill="both", expand=True)
        txt = tk.Text(body, wrap="word", font=("Consolas", 10),
                       bg=WHITE, relief="solid", borderwidth=1)
        txt.pack(fill="both", expand=True)

        bot = tk.Frame(dlg, bg=BG, padx=10, pady=10)
        bot.pack(fill="x")
        def _do_add():
            section = sec_var.get()
            if section not in self.sections:
                messagebox.showerror("Bad section", "Pick a valid section.", parent=dlg)
                return
            lines = [l.strip() for l in txt.get("1.0", "end-1c").splitlines()
                     if l.strip()]
            if not lines:
                dlg.destroy()
                return
            new_items = []
            for line in lines:
                item = self._wrap_item(line, False)
                self.sections[section].append(item)
                new_items.append(item)
            self._mark_dirty()
            # Append the new rows in-place rather than re-rendering the
            # entire APA (which used to wipe scroll position + flash
            # every section). Single-item add already uses this pattern
            # in `_add_item`; bulk-paste now mirrors it.
            widgets = self._section_widgets.get(section)
            if widgets:
                for item in new_items:
                    self._render_item_row(widgets["body"], item,
                                            self.sections[section],
                                            section_name=section)
                try:
                    widgets["add_row"].pack_forget()
                    widgets["add_row"].pack(fill="x")
                except tk.TclError:
                    pass
                if section in self._collapsed:
                    self._toggle_section(section)
                self._refresh_count_label(section)
                try:
                    self._scroll.attach_wheel(widgets["body"])
                except Exception:
                    pass
                self._refresh_scrollregion()
            else:
                # Section wasn't rendered (collapsed-and-empty case,
                # very rare) — fall back to a full render.
                self._render_all()
            dlg.destroy()
            show_toast(self, f"Added {len(lines)} items to {section}", kind="success")
        tk.Button(bot, text=f"Add", font=("Segoe UI Variable", 10, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=14, pady=4,
                  command=_do_add).pack(side="right")
        tk.Button(bot, text="Cancel", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                  padx=10, pady=4, command=dlg.destroy).pack(side="right", padx=(0, 6))

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.title(self._title_text(dirty=False))
        # Disable mousewheel changing Combobox values — prevents accidental
        # selection changes when the user scrolls the section list.
        try:
            self.unbind_class("TCombobox", "<MouseWheel>")
        except tk.TclError:
            pass
        self.build_header("SERVPRO  ·  APA Monitor",
                          subtitle=self.today.strftime("%A, %B %d, %Y"))

        # Path row + franchise filter row — flex onto a single row when
        # there's space, stack as two when the window is narrow.
        # Kept refs (`_path_label`) so the rollover handler can repoint
        # the label without a full UI rebuild — without that, you lose
        # the visual cue confirming which day the app is writing to.
        self._path_row = tk.Frame(self, bg=BG, padx=14, pady=6)
        self._path_row.pack(fill="x")
        ctkh.h2(self._path_row, "File").pack(side="left")
        self._path_label = ctkh.ctk.CTkLabel(
            self._path_row, text=self.doc_path,
            font=ctkh.ctk.CTkFont("Consolas", 10),
            text_color=GREEN_DARK, fg_color=BG)
        self._path_label.pack(side="left", padx=(8, 0))

        # Franchise filter — pinned above the section list. "All" = no
        # filter; any other value hides items whose franchise tag doesn't
        # match. Selection is persisted across reloads.
        self._build_franchise_filter_row()
        self._build_trello_search_row()
        # Estimator visibility chips — one per estimator, click to
        # toggle. Hidden estimators with 0 cards stay collapsed off
        # the section list, keeping the panel scannable when only a
        # few of the team have active work.
        self._build_estimator_chip_row()

        # Snap the franchise row to the right side of the path row when wide.
        ResponsiveSnap(self,
                       inline_parent=self._path_row,
                       narrow_parent=self._fr_row,
                       movable=self._fr_inner,
                       narrow_after=self._path_row)

        # Bottom bar — created BEFORE the scrollable body and packed to
        # the bottom so the action buttons are guaranteed to stay visible
        # even when the window is short. Buttons are added to it further
        # down once the rest of the layout has been built.
        bar = ResponsiveActionBar(self, root_widget=self,
                                  bg=BG, padx=14, pady=10)
        bar.pack(side="bottom", fill="x")

        # Scrollable body — ScrollableFrame uses a per-instance bindtag so
        # mousewheel events stay scoped to this panel (no leak into hidden
        # panels when the launcher swaps tools).
        scroll = ScrollableFrame(self, bg=BG, padx=8, pady=4)
        scroll.pack(fill="both", expand=True)
        self._canvas = scroll.canvas
        self._inner  = scroll.inner
        self._scroll = scroll

        # Action bar — only the daily-loop actions stay visible. Open,
        # Reload, Paste, and Contacts moved into the ⋯ More overflow menu
        # so the bar isn't visually overwhelming on narrow windows.
        save_btn = ctkh.btn(bar, "💾  Save to .docx", command=self._save,
                            kind="primary", width=170, height=36)
        bar.add(save_btn, group="primary", side="right", padx=(0, 0))

        self._saved_label = ctkh.ctk.CTkLabel(
            bar, text="not saved yet",
            font=ctkh.font(9), text_color=TEXT_GRAY, fg_color=BG)
        bar.add(self._saved_label, group="primary", side="right", padx=(0, 10))

        # ⋯ More — overflow menu for less-frequent actions.
        more = ctkh.MoreMenu(bar, label="⋯ More", width=100)
        more.add("Open current doc", icon="📁",
                 command=lambda: os.startfile(self.doc_path)
                 if os.path.isfile(self.doc_path)
                 else messagebox.showinfo("Not saved yet",
                       "Save first, then the file will exist.", parent=self))
        more.add("Reload from disk", icon="↻", command=self._reload)
        more.add_separator()
        more.add("Paste bulk dispatch…", icon="📋",
                 command=self._open_bulk_paste)
        more.add("Manage contacts…", icon="✉",
                 command=self._open_contacts_dialog)
        more.add("EOD recipients…", icon="📧",
                 command=self._open_eod_recipients_dialog)
        bar.add(more.button, group="secondary", side="left", padx=(0, 6))

        # Teams blue for send-all so the user reads it as Teams-flavored.
        send_all_btn = ctkh.btn(
            bar, "📨 Send All", command=self._send_teams_to_all,
            kind="primary", width=130,
            fg_color="#4A90D9", hover_color="#357ABD")
        bar.add(send_all_btn, group="secondary", side="left", padx=(0, 6))

        eod_btn = ctkh.btn(bar, "📧 EOD Email",
                           command=self._send_eod_email,
                           kind="primary", width=150)
        # Right-click EOD opens the recipients dialog — mirror of the
        # entry in the ⋯ More menu but kept here as a power-user shortcut.
        eod_btn.bind("<Button-3>",
                     lambda e: self._open_eod_recipients_dialog())
        bar.add(eod_btn, group="secondary", side="left", padx=(0, 6))

        # 👥 Manage estimators — add / reorder / remove the per-estimator
        # section rows. Persisted, survives restarts. Roster initially
        # comes from _DEFAULT_ESTIMATORS_ORDERED; any user edit overrides.
        manage_est_btn = ctkh.btn(
            bar, "👥 Manage estimators",
            command=self._open_manage_estimators_dialog,
            kind="ghost", width=170)
        bar.add(manage_est_btn, group="secondary", side="left", padx=(0, 6))

        # Tick the saved-label every 30s so "2 min ago" stays current
        self._tick_saved_label()

    def _reload(self):
        if messagebox.askyesno("Reload", "Discard unsaved changes and reload from disk?",
                                parent=self):
            self.sections = {s: [] for s in SECTION_ORDER}
            self.show_loading("Reloading APA doc…")
            try:
                self._load_from_doc()
                self._render_all()
            finally:
                self.hide_loading()

    # ── Franchise filter ────────────────────────────────────────────────────
    def _build_franchise_filter_row(self):
        """Combobox of franchise names + 'All'. Selection re-renders and
        persists. Refresh button reloads choices from persistence (in case
        the user added one via the Manage… dialog while the panel is open).

        The row's content lives inside `_fr_inner` so ResponsiveSnap can
        slide it onto the path row when the window has horizontal room.
        """
        self._fr_row = tk.Frame(self, bg=BG, padx=14)
        self._fr_row.pack(fill="x", pady=(0, 6))
        # Parent is `self`, not _fr_row, so ResponsiveSnap can re-pack it
        # into the path row via in_= (Tk requires the in_ target to be a
        # descendant of the slave's parent).
        self._fr_inner = tk.Frame(self, bg=BG)
        self._fr_inner.pack(in_=self._fr_row, side="left", anchor="w")
        tk.Label(self._fr_inner, text="Franchise:",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._franchise_filter_var = tk.StringVar(
            value=(self._franchise_filter or "All"))
        self._franchise_filter_cb = ttk.Combobox(
            self._fr_inner, textvariable=self._franchise_filter_var,
            state="readonly", width=24,
            values=self._franchise_filter_choices())
        self._franchise_filter_cb.pack(side="left", padx=(6, 4))
        self._franchise_filter_cb.bind(
            "<<ComboboxSelected>>", lambda e: self._on_franchise_filter_change())
        # Subtle "untagged" / count hint to the right of the dropdown
        self._franchise_filter_hint = tk.Label(
            self._fr_inner, text="", font=("Segoe UI Variable", 8, "italic"),
            bg=BG, fg=TEXT_GRAY)
        self._franchise_filter_hint.pack(side="left", padx=(6, 0))
        # Clear button — quick reset to "All" without opening the menu
        tk.Button(self._fr_inner, text="Clear", font=("Segoe UI Variable", 8),
                  bg=WHITE, fg=TEXT_DARK, relief="flat",
                  padx=8, pady=1, cursor="hand2",
                  command=self._clear_franchise_filter
                  ).pack(side="left", padx=(6, 0))
        self._update_franchise_filter_hint()

    # ── Estimator visibility chips ──────────────────────────────────────
    def _build_estimator_chip_row(self):
        """Row of one chip per estimator. Click toggles that estimator's
        section visible. Sections with ≥1 card are always shown (the
        cards force visibility); the chips are for surfacing EMPTY
        sections when the user wants to file something into them.

        Persisted to `apa_visible_estimators` so re-opens remember the
        override set. Chips re-render after every roster change (call
        `_rebuild_estimator_chips` from `_reload_estimators_cache` or
        the manage dialog save path)."""
        self._est_chip_row = tk.Frame(self, bg=BG, padx=14)
        self._est_chip_row.pack(fill="x", pady=(0, 6))
        tk.Label(self._est_chip_row, text="Estimators:",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._est_chip_inner = tk.Frame(self._est_chip_row, bg=BG)
        self._est_chip_inner.pack(side="left", padx=(6, 0))
        self._rebuild_estimator_chips()

    def _rebuild_estimator_chips(self):
        """Wipe + redraw the chip strip. Called from initial build and
        whenever the estimator roster changes (manage dialog save)."""
        if not getattr(self, "_est_chip_inner", None):
            return
        for w in self._est_chip_inner.winfo_children():
            try:
                w.destroy()
            except tk.TclError:
                pass
        for est in ESTIMATORS_ORDERED:
            forced = est in self._forced_visible_estimators
            has_cards = bool(self.sections.get(est) or [])
            # Chip's visual state: green-filled when "showing" (either
            # forced or has cards); muted when empty + not forced.
            if forced or has_cards:
                bg_c, fg_c, hover_c = SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER
            else:
                bg_c, fg_c, hover_c = SURFACE_2, TEXT_GRAY, NEUTRAL_HOVER
            initials = _estimator_initials(est)
            label = f"{initials}"
            if has_cards:
                # Card count badge inline — "FB 3" reads as a quick
                # workload signal even before scrolling to the section.
                label = f"{initials}  {len(self.sections[est])}"
            btn = tk.Button(
                self._est_chip_inner, text=label,
                font=("Segoe UI Variable", 8, "bold"),
                bg=bg_c, fg=fg_c,
                activebackground=hover_c, activeforeground=fg_c,
                relief="flat", padx=8, pady=3, cursor="hand2",
                command=lambda e=est: self._toggle_estimator_visibility(e))
            btn.pack(side="left", padx=(0, 4))
            tip = (f"{est} — {len(self.sections.get(est) or [])} "
                    "card(s). Click to "
                    + ("hide empty section."
                       if forced and not has_cards
                       else "show empty section."))
            try:
                from tool_panel import attach_tooltip as _tt
                _tt(btn, tip)
            except Exception:
                pass

    def _toggle_estimator_visibility(self, est):
        """Flip an estimator section's "forced visible" state. Empty
        sections that the user has toggled stay rendered; toggling
        back hides them again."""
        est = (est or "").strip().upper()
        if not est:
            return
        if est in self._forced_visible_estimators:
            self._forced_visible_estimators.discard(est)
        else:
            self._forced_visible_estimators.add(est)
        try:
            persistence.set_value(
                "apa_visible_estimators",
                sorted(self._forced_visible_estimators))
        except Exception:
            pass
        try:
            self._rebuild_estimator_chips()
        except Exception:
            pass
        try:
            self._render_all()
        except Exception:
            pass

    # ── Trello name-search → Add to APA ─────────────────────────────────────
    # User types/pastes a client name, hits Find → search Trello, suggest
    # an APA section based on the matched card's lane, confirm, append a
    # new row to the chosen section. Saves the manual "find which section
    # to add this to" step that was the daily workflow before.

    # Trello lane → APA section suggestion. Lanes that map cleanly are
    # listed; anything not here defaults to the user picking explicitly.
    _LANE_TO_SECTION = None  # populated lazily via _lane_section_map()

    def _lane_section_map(self):
        """Return {trello_lane_lower: apa_section_constant}. Built once
        per panel so a board rename doesn't require code edits — the
        lookup is case-insensitive substring."""
        if self._LANE_TO_SECTION is not None:
            return self._LANE_TO_SECTION
        # Order matters — the lookup walks dict insertion order doing a
        # substring match on the lane name (lowercased). Put MORE specific
        # keys first so e.g. "kim+esteban" matches before bare "kim", and
        # "al jr" matches before "samantha" on a lane named
        # "SAMANTHA / AL JR." (default-first-listed-name policy on combo
        # lanes — user can always override the dropdown).
        m = {
            # Estimating board lanes (high priority — must beat the
            # short-name estimator keys below)
            "add'l work":                     SEC_EST_MISSING,
            "additional items":               SEC_EST_MISSING,
            "missing items":                  SEC_EST_MISSING,
            "estimating missing":             SEC_EST_MISSING,
            "snapshot":                       SEC_EST_SNAPSHOT,
            "estimating snapshot":            SEC_EST_SNAPSHOT,
            "to be assigned":                 SEC_EST_TBA,
            "estimating tba":                 SEC_EST_TBA,
            "service call":                   SEC_EST_SERVICE_CALL,
            "service calls":                  SEC_EST_SERVICE_CALL,
            # Board has the typo "SERIVCE CALLS - STORM" — match anyway.
            "serivce call":                   SEC_EST_SERVICE_CALL,
            "estimating service call":        SEC_EST_SERVICE_CALL,
            "pending review":                 SEC_PENDING_REVIEW,

            # Estimator lanes — combo lanes default to FIRST listed name;
            # user can change in the dropdown. Two-token keys placed
            # before bare estimator keys so they win the substring race.
            "juantes":                        "JUAN",          # board lane name for Juan
            "kim+esteban":                    "KIM",            # combo → first listed
            "samantha / al jr":               "SAMANTHA",       # combo → first listed
            "samantha/al jr":                 "SAMANTHA",
            "al jr":                          "AARON L",        # AL JR. = Aaron L
            "aaron l":                        "AARON L",
            "juan":                           "JUAN",
            "aaron":                          "AARON",
            "johnny":                         "JOHNNY",
            "kim":                            "KIM",
            "zac":                            "ZAC",
            "esteban":                        "ESTEBAN",
            "victoria":                       "VICTORIA",
            "pablo":                          "PABLO",
            "samantha":                       "SAMANTHA",
            "recon":                          "RECON",

            # Other boards — most ongoing-job lanes route to Final
            # Uploads (per workflow: anything still in progress / on
            # hold / pending approval lives in Final until closed).
            # Initial Inspections / Re-Inspection / TBS New Loss are
            # the exception — those go to Initial Uploads.
            "initial inspections":            SEC_INITIAL_UPLOADS,
            "initial inspection":             SEC_INITIAL_UPLOADS,
            "re-inspection":                  SEC_INITIAL_UPLOADS,
            "tbs new loss":                   SEC_INITIAL_UPLOADS,
            "monitor":                        SEC_FINAL_UPLOADS,
            "work in progress":               SEC_FINAL_UPLOADS,
            "tbs mitigation":                 SEC_INITIAL_UPLOADS,
            "tbs contents":                   SEC_FINAL_UPLOADS,
            "test/clearance":                 SEC_FINAL_UPLOADS,
            "testing/clearance":              SEC_FINAL_UPLOADS,
            "on hold":                        SEC_FINAL_UPLOADS,
            "pending approval":               SEC_FINAL_UPLOADS,
            "pending ins":                    SEC_FINAL_UPLOADS,
            "selfpay":                        SEC_FINAL_UPLOADS,
            "self-pay":                       SEC_FINAL_UPLOADS,
            "self pay":                       SEC_FINAL_UPLOADS,
            "office questions":               SEC_FINAL_UPLOADS,
            "audit rejection":                SEC_AUDIT_REJECTION,
            "audit dispute":                  SEC_AUDIT_DISPUTE,
        }
        self._LANE_TO_SECTION = m
        return m

    def _suggest_apa_section(self, lane_name):
        """Best-guess APA section for a given Trello lane. Returns a
        section constant or empty string when there's no clean default
        (e.g. OFFICE QUESTIONS, CUSTOMER CONCERNS — user chooses)."""
        ln = (lane_name or "").strip().lower()
        if not ln:
            return ""
        m = self._lane_section_map()
        # Exact-ish prefix match first, then substring.
        if ln in m:
            return m[ln]
        for k, v in m.items():
            if k in ln:
                return v
        return ""

    # Trello lane → APA Sub-field default. Only lanes whose name maps
    # cleanly to a SUB_OPTIONS value go here; any lane not in this map
    # leaves the Sub field at the user-pick default. Keys are lowercase
    # substring matches (same lookup pattern as `_lane_section_map`).
    _LANE_TO_SUB = None

    def _lane_sub_map(self):
        if self._LANE_TO_SUB is not None:
            return self._LANE_TO_SUB
        m = {
            # Multi-word keys first so the substring walk doesn't let
            # short keys (e.g. "monitor") win against longer specific
            # ones (e.g. "monitor / sched").
            "initial inspections":     "Initial Inspections/Re-Inspections",
            "re-inspection":           "Initial Inspections/Re-Inspections",
            "tbs new loss":            "TBS New Loss/Re-Inspection",
            "tbs mitigation":          "TBS Mitigation",
            "tbs contents":            "TBS Contents",
            "testing/clearance":       "Testing/Clearance",
            "test/clearance":          "Testing/Clearance",
            "office questions":        "Office Questions",
            "pending approval":        "PENDING APROVAL/INS/SELFPAY",
            "pending ins":             "PENDING APROVAL/INS/SELFPAY",
            "selfpay":                 "PENDING APROVAL/INS/SELFPAY",
            "self-pay":                "PENDING APROVAL/INS/SELFPAY",
            "self pay":                "PENDING APROVAL/INS/SELFPAY",
            "pending approvals":       "Pending Approvals/Property Management",
            "property management":     "Pending Approvals/Property Management",
            "add'l work":              "Add'l Work/Missing Items",
            "additional items":        "Add'l Work/Missing Items",
            "missing items":           "Add'l Work/Missing Items",
            "upcoming":                "Upcoming/Pending",
            "on hold":                 "On Hold",
            "work in progress":        "Work in progress",
            "monitor":                 "Monitor",
            "initial":                 "Initial",
        }
        self._LANE_TO_SUB = m
        return m

    def _suggest_apa_sub(self, lane_name):
        """Best-guess Sub value for a given Trello lane (lanes like
        WORK IN PROGRESS / TBS Mitigation / Testing-Clearance match a
        SUB_OPTIONS entry directly). Returns "" when no clean match."""
        ln = (lane_name or "").strip().lower()
        if not ln:
            return ""
        m = self._lane_sub_map()
        if ln in m:
            return m[ln]
        for k, v in m.items():
            if k in ln:
                return v
        return ""

    def _build_trello_search_row(self):
        """Compact search field beneath the franchise filter. Enter or
        click 🔎 → fuzzy-find a Trello card by name → confirm dialog."""
        row = tk.Frame(self, bg=BG, padx=14)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text="Add by name:",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._trello_search_var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=self._trello_search_var,
                         width=32, font=("Segoe UI Variable", 9))
        ent.pack(side="left", padx=(6, 4))
        tk.Button(row, text="🔎 Find on Trello",
                  font=("Segoe UI Variable", 8, "bold"),
                  bg=SUCCESS_BG, fg=SUCCESS_FG,
                  activebackground=SUCCESS_HOVER,
                  relief="flat", padx=10, pady=2, cursor="hand2",
                  command=self._on_trello_search).pack(side="left")
        tk.Label(row,
                 text="Looks up Trello, suggests a section, then asks "
                      "you to confirm.",
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=BG, fg=TEXT_GRAY).pack(side="left", padx=(8, 0))
        ent.bind("<Return>", lambda _e: self._on_trello_search())

    def _on_trello_search(self):
        query = (self._trello_search_var.get() or "").strip()
        if not query:
            return
        try:
            import trello_client as tc
        except Exception as ex:
            messagebox.showerror("Trello unavailable",
                                  f"Couldn't load trello_client:\n{ex}",
                                  parent=self)
            return

        # Hit Trello on a thread so the panel stays responsive — the
        # /search round-trip can take a couple seconds on a slow link.
        import threading
        def _bg():
            try:
                hits = tc.find_cards_by_name(query, max_results=10) or []
                err = None
            except Exception as ex:
                hits, err = [], str(ex)
            def _done():
                if err:
                    messagebox.showerror(
                        "Trello search failed",
                        f"Couldn't reach Trello:\n\n{err}",
                        parent=self)
                    return
                if not hits:
                    messagebox.showinfo(
                        "No matches",
                        f"Trello returned no cards for {query!r}.\n\n"
                        "Try the last name only, or paste the card URL "
                        "directly via 📌 Pin on a row.",
                        parent=self)
                    return
                if len(hits) == 1:
                    self._open_add_to_apa_dialog(hits[0])
                else:
                    self._open_match_picker_dialog(hits)
            self.after(0, _done)
        threading.Thread(target=_bg, daemon=True).start()

    def _open_match_picker_dialog(self, hits):
        """Show a picker when the search returned >1 cards. Selecting
        one routes into the section-confirm dialog with that card."""
        dlg = tk.Toplevel(self)
        dlg.title("Pick a Trello card")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        try:
            dlg.geometry("520x420")
        except tk.TclError:
            pass

        tk.Label(dlg,
                 text=f"{len(hits)} matches — pick one to add to APA:",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 padx=14).pack(anchor="w", pady=(12, 6))

        listframe = tk.Frame(dlg, bg=WHITE,
                              highlightthickness=1, highlightbackground=BORDER)
        listframe.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        inner = ScrollableFrame(listframe, bg=WHITE, height=300)
        inner.pack(fill="both", expand=True)

        for h in hits:
            row = tk.Frame(inner.inner, bg=WHITE, padx=10, pady=6)
            row.pack(fill="x")
            tk.Label(row, text=h.get("name", "?"),
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=TEXT_DARK,
                     anchor="w").pack(fill="x")
            sub = h.get("list_name") or "?"
            tk.Label(row,
                     text=f"{h.get('board', '?')}  ·  {sub}",
                     font=("Segoe UI Variable", 8),
                     bg=WHITE, fg=TEXT_GRAY, anchor="w").pack(fill="x")
            tk.Button(row, text="Use this card",
                      font=("Segoe UI Variable", 8, "bold"),
                      bg=GREEN, fg=WHITE,
                      activebackground=GREEN_DARK,
                      relief="flat", padx=10, pady=3, cursor="hand2",
                      command=lambda hh=h, d=dlg:
                          (d.destroy(), self._open_add_to_apa_dialog(hh))
                      ).pack(anchor="e", pady=(2, 0))
            tk.Frame(inner.inner, bg=BORDER, height=1).pack(fill="x")

        tk.Button(dlg, text="Cancel",
                  font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_DARK,
                  activebackground=NEUTRAL_HOVER,
                  relief="solid", bd=1, padx=14, pady=4, cursor="hand2",
                  command=dlg.destroy).pack(side="right",
                                              padx=14, pady=(0, 12))

    def _open_add_to_apa_dialog(self, hit):
        """Confirm dialog: shows the matched card, suggests a section
        based on its Trello lane, lets the user pick section / sub /
        status, and on Confirm appends a populated row to that section.

        `hit` is one element from `find_cards_by_name`'s return list:
        {board, card_id, name, url, list_id, list_name}."""
        card_name  = hit.get("name", "")
        lane_name  = hit.get("list_name", "")
        suggested  = self._suggest_apa_section(lane_name)
        # Default item text is the card name minus any trailing carrier
        # OR self-pay suffix — matches the format APA rows are typed in.
        item_text = card_name.strip()

        dlg = tk.Toplevel(self)
        dlg.title("Add to APA Monitor")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        try:
            dlg.geometry("520x460")
            dlg.resizable(False, False)
        except tk.TclError:
            pass

        # ── Header: card identity ────────────────────────────────────
        head = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        head.pack(fill="x")
        tk.Label(head, text="📋 Found on Trello",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=BG, fg=TEXT_GRAY).pack(anchor="w")
        tk.Label(head, text=card_name,
                 font=("Segoe UI Variable", 12, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 wraplength=480, justify="left",
                 anchor="w").pack(fill="x", pady=(2, 0))
        tk.Label(head,
                 text=f"Board: {hit.get('board') or '?'}   ·   "
                      f"Lane: {lane_name or '?'}",
                 font=("Segoe UI Variable", 8),
                 bg=BG, fg=TEXT_GRAY).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(dlg, bg=BG, padx=14)
        body.pack(fill="both", expand=True)

        # ── Section dropdown ─────────────────────────────────────────
        tk.Label(body, text="APA section:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 anchor="w").pack(fill="x", pady=(8, 2))
        # Order matches APA doc top-to-bottom; Pending Review skipped
        # because it's an estimator-routed bucket, not user-typed.
        sec_choices = [
            SEC_FINAL_UPLOADS,
            SEC_EST_MISSING, SEC_EST_SERVICE_CALL,
            SEC_EST_TBA, SEC_EST_SNAPSHOT,
            *ESTIMATORS_ORDERED,
            SEC_INITIAL_UPLOADS, SEC_DAILY_UPLOADS,
            SEC_AUDIT_REJECTION, SEC_AUDIT_DISPUTE,
        ]
        sec_var = tk.StringVar(value=suggested or sec_choices[0])
        sec_cb = ttk.Combobox(body, textvariable=sec_var,
                               values=sec_choices, state="readonly",
                               width=42, font=("Segoe UI Variable", 9))
        sec_cb.pack(anchor="w")
        suggest_lbl = tk.Label(
            body,
            text=(f"Suggested from Trello lane: {lane_name!r}"
                  if suggested else
                  "No clean suggestion for this lane — pick one above."),
            font=("Segoe UI Variable", 8, "italic"),
            bg=BG, fg=TEXT_GRAY, anchor="w")
        suggest_lbl.pack(fill="x", pady=(2, 8))

        # ── Item text ────────────────────────────────────────────────
        tk.Label(body, text="Row text (client + carrier):",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 anchor="w").pack(fill="x", pady=(0, 2))
        text_var = tk.StringVar(value=item_text)
        ttk.Entry(body, textvariable=text_var,
                  width=58, font=("Segoe UI Variable", 9)).pack(anchor="w")

        # ── Sub + Status (depend on section) ─────────────────────────
        sub_status_box = tk.Frame(body, bg=BG)
        sub_status_box.pack(fill="x", pady=(8, 0))
        sub_var    = tk.StringVar()
        status_var = tk.StringVar()
        sub_lbl    = tk.Label(sub_status_box, text="Sub:",
                               font=("Segoe UI Variable", 9, "bold"),
                               bg=BG, fg=TEXT_DARK)
        sub_cb     = ttk.Combobox(sub_status_box, textvariable=sub_var,
                                   width=22, font=("Segoe UI Variable", 9))
        status_lbl = tk.Label(sub_status_box, text="Status:",
                               font=("Segoe UI Variable", 9, "bold"),
                               bg=BG, fg=TEXT_DARK)
        status_cb  = ttk.Combobox(sub_status_box, textvariable=status_var,
                                   width=14, font=("Segoe UI Variable", 9),
                                   state="readonly")

        def _refresh_sub_status(*_a):
            sec = sec_var.get()
            sub_opts = _sub_options_for_section(sec)
            for w in (sub_lbl, sub_cb): w.pack_forget()
            for w in (status_lbl, status_cb): w.pack_forget()
            if sub_opts is not None:
                sub_lbl.pack(side="left")
                sub_cb.pack(side="left", padx=(4, 12))
                sub_cb.config(values=sub_opts)
                if sub_var.get() not in sub_opts:
                    sub_var.set("")
            status_lbl.pack(side="left")
            status_cb.pack(side="left", padx=(4, 0))
            status_opts = _status_options_for_section(sec)
            status_cb.config(values=status_opts)
            if status_var.get() not in status_opts:
                status_var.set("")
        _refresh_sub_status()
        # Sub default rules — applied AFTER _refresh_sub_status so the
        # value isn't cleared by the "value not in dropdown opts" logic.
        # Only fired when the suggested section actually shows a Sub
        # field (estimator sections / ESTIMATING * have None — auto-
        # filling there would save an invisible value).
        # Order:
        #   1. Lane has a clean SUB_OPTIONS match (Work in progress,
        #      TBS Mitigation, Testing/Clearance, etc.) → use that.
        #   2. Lane has no APA-section mapping → fall back to the
        #      verbatim lane name (so the user picks a section but
        #      keeps the lane context in Sub).
        # User can always edit / clear before saving.
        if _sub_options_for_section(sec_var.get()) is not None:
            sub_default = self._suggest_apa_sub(lane_name)
            if sub_default:
                sub_var.set(sub_default)
            elif not suggested and lane_name:
                sub_var.set(lane_name)
        sec_var.trace_add("write", _refresh_sub_status)

        # ── Buttons ──────────────────────────────────────────────────
        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(fill="x", side="bottom")

        def _confirm():
            sec = sec_var.get()
            txt = (text_var.get() or "").strip()
            if not sec or not txt:
                messagebox.showerror(
                    "Missing fields",
                    "Pick a section and enter row text.",
                    parent=dlg)
                return
            self._append_row_to_section(
                sec, text=txt,
                sub=sub_var.get() or "",
                status=status_var.get() or "")
            # Pin the Trello card to this client so future autofill /
            # 📌 lookups use this card without re-searching.
            try:
                cid = hit.get("card_id")
                if cid:
                    base = _strip_to_base(txt)
                    persistence.set_trello_card_ids(base, [cid])
            except Exception:
                pass
            try:
                show_toast(self,
                           f"Added to {sec}", kind="success")
            except Exception:
                pass
            self._trello_search_var.set("")
            dlg.destroy()

        tk.Button(bot, text="Cancel",
                  font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_DARK,
                  activebackground=NEUTRAL_HOVER,
                  relief="solid", bd=1, padx=14, pady=5, cursor="hand2",
                  command=dlg.destroy).pack(side="right", padx=(8, 0))
        tk.Button(bot, text="Add to APA",
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=GREEN, fg=WHITE,
                  activebackground=GREEN_DARK, activeforeground=WHITE,
                  relief="flat", padx=18, pady=5, cursor="hand2",
                  command=_confirm).pack(side="right")

    def _append_row_to_section(self, section_name, *, text, sub, status):
        """Append a populated row to `section_name` and render it
        in-place (no full panel re-render). Mirrors `_add_item`'s flow
        but with pre-filled values so the user doesn't have to type
        them after the row appears."""
        widgets = self._section_widgets.get(section_name)
        items = self.sections.setdefault(section_name, [])
        new_item = {
            "text":      text,
            "sub":       sub,
            "status":    status,
            "franchise": "",
        }
        items.append(new_item)
        self._mark_dirty()
        if not widgets:
            self._render_all()
            return
        self._render_item_row(widgets["body"], new_item, items,
                              section_name=section_name)
        try:
            widgets["add_row"].pack_forget()
            widgets["add_row"].pack(fill="x")
        except tk.TclError:
            pass
        if section_name in self._collapsed:
            self._toggle_section(section_name)
        self._refresh_count_label(section_name)
        try:
            self._scroll.attach_wheel(widgets["body"])
        except Exception:
            pass
        self._refresh_scrollregion()

    def _franchise_filter_choices(self):
        """Build the dropdown values: All, (Untagged), then each franchise."""
        franchises = persistence.get_franchise_list() or []
        return ["All", "(Untagged)"] + list(franchises)

    def _refresh_franchise_filter_choices(self):
        """Pull the current franchise list into the combobox without losing
        the active selection (unless that selection no longer exists)."""
        if not self._franchise_filter_var:
            return
        choices = self._franchise_filter_choices()
        try:
            self._franchise_filter_cb.config(values=choices)
        except tk.TclError:
            return
        cur = self._franchise_filter_var.get()
        if cur not in choices:
            self._franchise_filter_var.set("All")
            self._franchise_filter = ""
            persistence.set_apa_franchise_filter("")

    def _on_franchise_filter_change(self):
        sel = self._franchise_filter_var.get()
        if sel == "All":
            self._franchise_filter = ""
        else:
            self._franchise_filter = sel
        persistence.set_apa_franchise_filter(self._franchise_filter)
        self._render_all()
        self._update_franchise_filter_hint()

    def _clear_franchise_filter(self):
        if self._franchise_filter_var:
            self._franchise_filter_var.set("All")
        self._franchise_filter = ""
        persistence.set_apa_franchise_filter("")
        self._render_all()
        self._update_franchise_filter_hint()

    def _update_franchise_filter_hint(self):
        """Show 'showing N of M items' to the right of the dropdown so the
        user can see at a glance how aggressive the filter is."""
        if not getattr(self, "_franchise_filter_hint", None):
            return
        total = sum(
            1 for items in self.sections.values()
            for it in items if it["text"].strip() or it["status"])
        if not self._franchise_filter:
            txt = f"{total} item(s)"
        else:
            shown = sum(
                1 for items in self.sections.values()
                for it in items
                if (it["text"].strip() or it["status"])
                and self._item_matches_filter(it))
            txt = f"showing {shown} of {total}"
        try:
            self._franchise_filter_hint.config(text=txt)
        except tk.TclError:
            pass

    def _item_matches_filter(self, item):
        """Apply the active franchise filter to a single item dict."""
        f = self._franchise_filter
        if not f:
            return True
        tag = (item.get("franchise") or "").strip()
        if f == "(Untagged)":
            return not tag
        return tag == f

    def _visible_items(self, items):
        """Apply the franchise filter to a section's items list.

        Empty placeholder rows (no text + no status) always render so the
        user can edit them — filtering them out would hide brand-new
        rows-in-progress."""
        if not self._franchise_filter:
            return items
        return [it for it in items
                if self._item_matches_filter(it)
                or not (it["text"].strip() or it["status"])]

    # ── Render ──────────────────────────────────────────────────────────────
    def _render_all(self):
        # Save scroll position so add/delete/collapse doesn't jump back to top
        saved_yview = None
        try:
            saved_yview = self._canvas.yview()
        except (AttributeError, tk.TclError):
            pass

        # Refresh chip strip — card counts on chips reflect current
        # section state ("FB 3"). Cheap; just iterates the roster.
        try:
            self._rebuild_estimator_chips()
        except Exception:
            pass

        for w in self._inner.winfo_children():
            w.destroy()
        self._section_widgets = {}

        # One-time legend at top of scroll area
        legend = tk.Frame(self._inner, bg=BG, padx=10, pady=4)
        legend.pack(fill="x", pady=(2, 4))
        tk.Label(legend,
                 text="🏢 franchise tag  ·  Client-Carrier  ·  Category  "
                      "·  Status  ·  pending = highlighted yellow",
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=BG, fg=TEXT_GRAY).pack(anchor="w")

        for name in SECTION_ORDER:
            # Snapshot-style pastel headers — subtler than the old solid
            # green/blue blocks, with dark text instead of white.
            if name in ESTIMATOR_SECTIONS:
                hdr_bg, hdr_fg = LINK_BG, LINK_FG
            elif name in AUDIT_SECTIONS:
                hdr_bg, hdr_fg = DANGER_BG, DANGER_FG
            else:
                hdr_bg, hdr_fg = SUCCESS_BG, SUCCESS_FG
            self._render_section(name, self.sections[name],
                                 lambda n=name: self.sections[n],
                                 bg_header=hdr_bg, fg_header=hdr_fg)

        # Force the inner frame to lay out its children NOW so the scrollregion
        # bbox is correct before we restore yview — otherwise the canvas
        # clamps to a stale (smaller) bbox and the page snaps to the top, which
        # also shows up as "frames break" when the user scrolls during a render.
        self.update_idletasks()
        try:
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        except tk.TclError:
            pass

        # Re-attach mouse-wheel bindtag to every freshly-created child
        self._scroll.attach_wheel(self._inner)

        # Sweep tooltips after every render so freshly spawned row
        # buttons (💬, 📌, 🏢, ✨, ×) pick up default hover hints.
        try:
            self.after_idle(self.sweep_tooltips)
        except Exception:
            pass

        # Restore scroll position after the UI has laid itself out
        if saved_yview:
            try:
                self._canvas.yview_moveto(saved_yview[0])
            except tk.TclError:
                pass

    def _render_section(self, title, items, items_getter,
                         bg_header=None, fg_header=None):
        bg_header = bg_header or "#E8F5EE"
        fg_header = fg_header or GREEN_DARK

        visible = self._visible_items(items)
        total = len([i for i in items if i["text"].strip() or i["status"]])
        shown = len([i for i in visible if i["text"].strip() or i["status"]])

        # When a franchise filter is active, hide entire sections that have
        # no matching items — the header would otherwise be visual noise.
        if self._franchise_filter and shown == 0:
            return

        # Estimator-section visibility — hide empty estimator sections
        # unless the user has clicked the matching chip up top. Built-in
        # sections (Final/Initial/Daily Uploads, Audit Rejection/Dispute,
        # Pending Review, etc.) always render so the user can file work
        # into them; only the per-estimator rows get this treatment.
        if (title in ESTIMATOR_SECTIONS
                and total == 0
                and title not in self._forced_visible_estimators):
            return

        wrap = tk.Frame(self._inner, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="x", padx=8, pady=(6, 0))

        header = tk.Frame(wrap, bg=bg_header, padx=14, pady=8, cursor="hand2")
        header.pack(fill="x")

        collapsed = title in self._collapsed
        arrow = "▶" if collapsed else "▼"
        count_txt = (f"({shown}/{total})"
                     if self._franchise_filter and shown != total
                     else f"({total})")
        lbl = tk.Label(header, text=f"{arrow}  {title}  {count_txt}",
                       font=("Segoe UI Variable", 10, "bold"),
                       bg=bg_header, fg=fg_header, cursor="hand2")
        lbl.pack(side="left")
        def _toggle(t=title):
            self._toggle_section(t)
        header.bind("<Button-1>", lambda e: _toggle())
        lbl.bind("<Button-1>", lambda e: _toggle())

        # Estimator section header gets a "💬 Message all" button
        if title in ESTIMATOR_SECTIONS and total > 0:
            def _msg_all(est=title):
                self._send_teams_to_estimator(est)
            tk.Button(header, text="💬  Message all",
                      font=("Segoe UI Variable", 8, "bold"),
                      bg=WHITE, fg=fg_header,
                      activebackground=WHITE, relief="flat",
                      padx=10, pady=2, cursor="hand2",
                      command=_msg_all).pack(side="right")

        # Audit section header gets a "💬 Send to estimators" button —
        # walks the items, groups by sub, opens one Teams chat per estimator.
        if title in AUDIT_SECTIONS and total > 0:
            def _msg_audit(sec=title):
                self._send_teams_for_audit_section(sec)
            tk.Button(header, text="💬  Send to estimators",
                      font=("Segoe UI Variable", 8, "bold"),
                      bg=WHITE, fg=fg_header,
                      activebackground=WHITE, relief="flat",
                      padx=10, pady=2, cursor="hand2",
                      command=_msg_audit).pack(side="right")

        body = tk.Frame(wrap, bg=WHITE, padx=10, pady=8)
        if not collapsed:
            body.pack(fill="x")
        for item in visible:
            self._render_item_row(body, item, items, section_name=title)

        # Add new — subtle pill button matching the section accent color
        add_row = tk.Frame(body, bg=WHITE, pady=4)
        add_row.pack(fill="x", pady=(6, 0))
        def _add(sec=title):
            self._add_item(sec)
        tk.Button(add_row, text="+  Add Item",
                  font=("Segoe UI Variable", 8, "bold"),
                  bg=bg_header, fg=fg_header,
                  activebackground=bg_header, activeforeground=fg_header,
                  relief="flat", padx=12, pady=3, cursor="hand2",
                  command=_add).pack(side="left")

        self._section_widgets[title] = {"body": body, "count_lbl": lbl,
                                        "add_row": add_row, "items": items}

    def _toggle_section(self, title):
        """Collapse/expand without rebuilding the section tree.

        Old code re-rendered the whole APA — every section, every row — on
        every toggle, which flashed the UI and lost focus. Now we just
        pack_forget/pack the body and update the arrow in the header label.
        """
        widgets = self._section_widgets.get(title)
        if not widgets or not widgets.get("body"):
            return
        if title in self._collapsed:
            self._collapsed.discard(title)
            try:
                widgets["body"].pack(fill="x")
            except tk.TclError:
                pass
        else:
            self._collapsed.add(title)
            try:
                widgets["body"].pack_forget()
            except tk.TclError:
                pass
        self._refresh_count_label(title)
        self._refresh_scrollregion()

    def _refresh_count_label(self, section_name):
        """Update '(N)' suffix in the section header without rebuilding.

        When a franchise filter is active, shows '(shown/total)' so the
        user can see at a glance how many items are hidden by the filter."""
        widgets = self._section_widgets.get(section_name)
        if not widgets:
            return
        items = widgets["items"]
        total = len([i for i in items if i["text"].strip() or i["status"]])
        if self._franchise_filter:
            shown = len([i for i in items
                         if (i["text"].strip() or i["status"])
                         and self._item_matches_filter(i)])
            count_txt = (f"({shown}/{total})"
                         if shown != total else f"({total})")
        else:
            count_txt = f"({total})"
        collapsed = section_name in self._collapsed
        arrow = "▶" if collapsed else "▼"
        try:
            widgets["count_lbl"].config(
                text=f"{arrow}  {section_name}  {count_txt}")
        except tk.TclError:
            pass
        self._update_franchise_filter_hint()

    def _add_item(self, section_name):
        """Append a new item to the section in-place — no full re-render."""
        widgets = self._section_widgets.get(section_name)
        items = self.sections[section_name]
        new_item = {"text": "", "sub": "", "status": "", "franchise": ""}
        items.append(new_item)
        self._mark_dirty()
        if not widgets:
            return
        self._render_item_row(widgets["body"], new_item, items,
                              section_name=section_name)
        # Keep "+ Add Item" at the bottom
        try:
            widgets["add_row"].pack_forget()
            widgets["add_row"].pack(fill="x")
        except tk.TclError:
            pass
        # If the section was collapsed, expand it so the user sees the new row.
        if section_name in self._collapsed:
            self._toggle_section(section_name)
        self._refresh_count_label(section_name)
        self._scroll.attach_wheel(widgets["body"])
        self._refresh_scrollregion()

    def _refresh_scrollregion(self):
        """Recompute scrollregion after surgical row inserts/removals."""
        try:
            self.update_idletasks()
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        except tk.TclError:
            pass

    # ── Franchise tag handlers ──────────────────────────────────────────────
    def _open_apa_note_dialog(self, client_base, section, refresh_btn):
        """Modal to edit the per-(client, section) Teams-message note. The
        note is appended to outgoing Teams messages for this row (per-item,
        per-section, per-estimator, Send All) and never written to the .docx.

        Args:
            client_base: canonical "Last, First - Carrier" — _strip_to_base
                applied at click time so inline-edited rows route to the
                right key.
            section: SEC_AUDIT_REJECTION or SEC_AUDIT_DISPUTE.
            refresh_btn: callable that repaints the row's 📝 indicator
                after Save / Clear.
        """
        dlg = tk.Toplevel(self)
        dlg.title(f"{section} note — {client_base}")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        try:
            dlg.geometry("520x340")
        except tk.TclError:
            pass

        try:
            existing = persistence.get_apa_message_note(client_base, section)
        except Exception:
            existing = ""

        header = tk.Label(
            dlg,
            text=("Appended to the Teams message for this "
                  f"{section.lower()}. Not written to the audit doc."),
            font=("Segoe UI Variable", 9),
            fg=TEXT_GRAY, bg=BG,
            wraplength=480, justify="left",
            anchor="w")
        header.pack(fill="x", padx=SPACE_L, pady=(SPACE_M, SPACE_XS))

        text_frame = tk.Frame(dlg, bg=BG)
        text_frame.pack(fill="both", expand=True,
                         padx=SPACE_L, pady=(0, SPACE_S))

        txt = tk.Text(text_frame, wrap="word",
                       font=("Segoe UI Variable", 10),
                       bg=WHITE, fg=TEXT_DARK,
                       relief="solid", bd=1,
                       padx=SPACE_S, pady=SPACE_XS,
                       undo=True)
        txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(text_frame, orient="vertical", command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set)
        if existing:
            txt.insert("1.0", existing)
        txt.focus_set()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(fill="x", padx=SPACE_L, pady=(0, SPACE_M))

        def _save(_=None):
            val = txt.get("1.0", "end-1c")
            try:
                persistence.set_apa_message_note(client_base, section, val)
            except Exception as ex:
                messagebox.showerror(
                    "Save failed",
                    f"Could not save note: {ex}", parent=dlg)
                return
            try:
                refresh_btn()
            except Exception:
                pass
            show_toast(self,
                       "Note saved" if val.strip() else "Note cleared",
                       kind="success")
            dlg.destroy()

        def _clear():
            txt.delete("1.0", "end")

        def _cancel():
            dlg.destroy()

        tk.Button(btn_row, text="Cancel", command=_cancel,
                   bg=SURFACE_2, fg=TEXT_DARK,
                   activebackground=NEUTRAL_HOVER,
                   relief="flat", padx=12, pady=4,
                   font=("Segoe UI Variable", 9)
                   ).pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Save", command=_save,
                   bg=SUCCESS_BG, fg=SUCCESS_FG,
                   activebackground=SUCCESS_HOVER,
                   relief="flat", padx=14, pady=4,
                   font=("Segoe UI Variable", 9, "bold")
                   ).pack(side="right")
        tk.Button(btn_row, text="Clear", command=_clear,
                   bg=WARN_BG, fg=WARN_FG,
                   activebackground=NEUTRAL_HOVER,
                   relief="flat", padx=10, pady=4,
                   font=("Segoe UI Variable", 9)
                   ).pack(side="left")

        dlg.bind("<Control-Return>", _save)
        dlg.bind("<Escape>", lambda _e: _cancel())

    def _set_item_franchise(self, item, franchise, refresh_btn):
        """Update an item's franchise tag and persist the mapping."""
        item["franchise"] = franchise
        try:
            persistence.set_franchise_tag(
                _franchise_key(item.get("text", "")), franchise)
        except Exception:
            pass
        self._mark_dirty()
        try:
            refresh_btn()
        except Exception:
            pass
        # If a franchise filter is active, the row's visibility may have
        # just flipped — re-render so the list stays consistent.
        if self._franchise_filter:
            self._render_all()
        else:
            self._update_franchise_filter_hint()

    def _open_franchise_manager(self, refresh_btn):
        """Modal to add/remove franchise names — local-only, immediately
        reflected on every visible row's badge popup."""
        dlg = tk.Toplevel(self)
        dlg.title("Manage Franchises")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        try:
            dlg.geometry("360x420")
        except tk.TclError:
            pass

        tk.Label(dlg, text="Franchises (local labels — never saved to the .docx)",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK, padx=14, pady=10
                 ).pack(anchor="w")

        list_card = tk.Frame(dlg, bg=WHITE,
                              highlightthickness=1, highlightbackground=BORDER)
        list_card.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        list_inner = tk.Frame(list_card, bg=WHITE)
        list_inner.pack(fill="both", expand=True, padx=8, pady=8)

        def _redraw():
            for w in list_inner.winfo_children():
                w.destroy()
            franchises = persistence.get_franchise_list()
            if not franchises:
                tk.Label(list_inner,
                         text="No franchises yet — add one below.",
                         font=("Segoe UI Variable", 9, "italic"),
                         bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")
                return
            for fr in franchises:
                row = tk.Frame(list_inner, bg=WHITE)
                row.pack(fill="x", pady=2)
                bg_pill, fg_pill = _franchise_colors(fr)
                tk.Label(row, text=f"  {fr}  ",
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=bg_pill, fg=fg_pill, padx=6, pady=2
                         ).pack(side="left")

                def _remove(name=fr):
                    if not messagebox.askyesno(
                            "Remove franchise",
                            f"Remove '{name}' from the franchise list?\n\n"
                            "Existing item tags pointing at this franchise "
                            "won't be changed automatically.",
                            parent=dlg):
                        return
                    cur = persistence.get_franchise_list()
                    cur = [x for x in cur if x != name]
                    persistence.set_franchise_list(cur)
                    _redraw()
                tk.Button(row, text="×", font=("Segoe UI Variable", 9, "bold"),
                          bg=WHITE, fg=FLAG_RED, relief="flat", width=2,
                          activebackground=WHITE,
                          command=_remove).pack(side="right")

        _redraw()

        add_row = tk.Frame(dlg, bg=BG)
        add_row.pack(fill="x", padx=14, pady=(0, 10))
        new_var = tk.StringVar()
        ent = tk.Entry(add_row, textvariable=new_var, font=("Segoe UI Variable", 10))
        ent.pack(side="left", fill="x", expand=True)

        def _add():
            name = new_var.get().strip()
            if not name:
                return
            cur = persistence.get_franchise_list()
            if name not in cur:
                cur.append(name)
                persistence.set_franchise_list(cur)
            new_var.set("")
            _redraw()
        tk.Button(add_row, text="+ Add", font=("Segoe UI Variable", 9, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=10, pady=4,
                  command=_add).pack(side="left", padx=(6, 0))
        ent.bind("<Return>", lambda e: _add())

        def _close_manager():
            # Pull any new/removed franchises into the top-of-panel
            # filter dropdown before closing.
            self._refresh_franchise_filter_choices()
            dlg.destroy()
        tk.Button(dlg, text="Close", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                  padx=10, pady=4, command=_close_manager
                  ).pack(side="right", padx=14, pady=(0, 12))
        dlg.protocol("WM_DELETE_WINDOW", _close_manager)

    def _autofill_row_from_trello(self, *, item, section_name,
                                   text_var, sub_var, status_var, sub_opts):
        """Only-fill-empty autofill: pull the matching Trello card and
        populate text-carrier suffix, `sub` (from lane), and `status`
        (from labels) for fields the user has left blank.

        Source-of-truth selection:
          1. If the client has pinned card_ids, use the first one.
          2. Otherwise, fuzzy-search by client base name and use the top hit.
          3. If neither finds anything, show a toast and bail.
        """
        base = _strip_to_base(item.get("text", "")) if item.get("text") else ""
        if not base:
            show_toast(self, "Type a client name first", kind="info")
            return

        try:
            import trello_client as tc
        except Exception as ex:
            show_toast(self, f"Trello client unavailable: {ex}", kind="error")
            return

        card_id = None
        try:
            pinned = persistence.get_trello_card_ids(base)
        except Exception:
            pinned = []
        if pinned:
            card_id = pinned[0]
        else:
            try:
                hits = tc.find_cards_by_name(base, max_results=5)
            except Exception as ex:
                show_toast(self, f"Trello search failed: {ex}", kind="error")
                return
            if not hits:
                show_toast(self,
                           f"No Trello card found for '{base}'. "
                           "Pin one with 📌 first.", kind="info")
                return
            card_id = hits[0].get("id")

        try:
            card = tc.get_card(card_id, actions_limit=10)
        except Exception as ex:
            show_toast(self, f"Couldn't load card: {ex}", kind="error")
            return
        if not card:
            show_toast(self, "Trello card not found (may have been archived)",
                       kind="error")
            return

        filled = []

        # 1. Carrier suffix in `text` — append " - CARRIER" only if the
        #    user typed just the client base (no " - " separator yet).
        cur_text = item.get("text", "").strip()
        if cur_text and " - " not in cur_text:
            card_name = (card.get("name") or "").strip()
            if " - " in card_name:
                suffix = card_name.split(" - ", 1)[1].strip()
                if suffix:
                    new_text = f"{cur_text} - {suffix}"
                    item["text"] = new_text
                    text_var.set(new_text)
                    filled.append("carrier")

        # 2. `sub` — match the card's current lane name against the
        #    section's allowed sub options (case-insensitive exact match).
        if (sub_var is not None and sub_opts
                and not item.get("sub", "").strip()):
            try:
                lane = tc.get_lane_name(card.get("idBoard", ""),
                                         card.get("idList", ""))
            except Exception:
                lane = ""
            if lane:
                lane_norm = lane.strip().lower()
                for opt in sub_opts:
                    if opt and opt.strip().lower() == lane_norm:
                        item["sub"] = opt
                        sub_var.set(opt)
                        filled.append("sub")
                        break

        # 3. `status` — only fill from explicit Trello labels (e.g. a
        #    label literally named "uploaded" or "pending"). We don't
        #    scan comment text — too noisy and easy to misread.
        if not item.get("status", "").strip():
            label_names = [
                (l.get("name") or "").strip().lower()
                for l in (card.get("labels") or [])
            ]
            status_opts = _status_options_for_section(section_name)
            for opt in status_opts:
                if opt and opt.strip().lower() in label_names:
                    item["status"] = opt
                    status_var.set(opt)
                    filled.append("status")
                    break

        if filled:
            self._mark_dirty()
            show_toast(self, f"Filled: {', '.join(filled)}", kind="success")
        else:
            show_toast(self,
                       "Nothing to fill — all fields already set "
                       "(or no Trello data matched)", kind="info")

    def _render_item_row(self, parent, item, items_list, section_name=""):
        """Client-Carrier | Sub (if applicable) | Status | (💬 if estimator) | ×
        Row auto-highlights yellow when status is pending/pending upload."""
        def _bg_for(status):
            return "#FFF8C4" if status.lower() in HIGHLIGHT_STATUSES else WHITE

        row_bg = _bg_for(item.get("status", ""))
        row = tk.Frame(parent, bg=row_bg)
        row.pack(fill="x", pady=2)

        # Track widgets whose bg needs to track the row's highlight state
        bg_tracked = [row]

        # Delete button — far right
        def _del(lst=items_list, it=item, r=row, sec=section_name):
            if it in lst:
                lst.remove(it)
            self._mark_dirty()
            try:
                r.destroy()
            except tk.TclError:
                pass
            self._refresh_count_label(sec)
            self._refresh_scrollregion()
        del_btn = tk.Button(row, text="×", font=("Segoe UI Variable", 9, "bold"),
                            bg=row_bg, fg=FLAG_RED, relief="flat", width=2,
                            activebackground=row_bg,
                            command=_del)
        del_btn.pack(side="right", padx=(2, 0))
        bg_tracked.append(del_btn)

        # Teams message button — estimator sections always; audit sections
        # only when a sub-estimator has been picked for this row. For audit
        # sections we still create the button up-front so the sub-dropdown
        # trace can show/hide it without rebuilding the row.
        msg_btn = None
        if section_name in ESTIMATOR_SECTIONS or section_name in AUDIT_SECTIONS:
            def _msg(it=item, sec=section_name):
                if sec in ESTIMATOR_SECTIONS:
                    est = sec
                else:
                    est = it.get("sub", "").strip()
                if not est:
                    return
                self._send_teams_about_item(est, it, section=sec)
            msg_btn = tk.Button(row, text="💬", font=("Segoe UI Variable", 9),
                                 bg=row_bg, fg=INFO_FG,
                                 activebackground=row_bg,
                                 relief="flat", padx=2, cursor="hand2",
                                 command=_msg)
            # Only show right away if it has a target; in audit sections
            # we wait until a sub is picked.
            if section_name in ESTIMATOR_SECTIONS or item.get("sub", "").strip():
                msg_btn.pack(side="right", padx=(0, 2))
            bg_tracked.append(msg_btn)
            attach_tooltip(
                msg_btn,
                "Open a pre-filled Teams message about this job")

        # 📝 Note — Audit Dispute / Audit Rejection only. Adds free-form
        # context that's APPENDED to the outgoing Teams message but never
        # written into the .docx audit. Lets the user paste line-item
        # rejection reasons or "see email Chain" without polluting the
        # daily doc. Stored in state.json keyed on the canonical client +
        # section so notes survive reloads and follow inline text edits.
        note_btn = None
        if section_name in AUDIT_SECTIONS:
            note_btn = tk.Button(row, text="📝",
                                  font=("Segoe UI Variable", 9),
                                  bg=row_bg, activebackground=row_bg,
                                  relief="flat", padx=2, cursor="hand2")
            note_btn.pack(side="right", padx=(0, 2))
            bg_tracked.append(note_btn)

            def _refresh_note_btn(it=item, sec=section_name, b=note_btn):
                base = _strip_to_base(it.get("text", "") or "")
                has = bool(base) and persistence.has_apa_message_note(base, sec)
                try:
                    b.config(
                        text="📝" + ("•" if has else ""),
                        fg=GREEN_DARK if has else TEXT_MUTED,
                        font=("Segoe UI Variable",
                              9, "bold" if has else "normal"))
                except tk.TclError:
                    pass

            def _open_note_dialog(it=item, sec=section_name,
                                   refresh=_refresh_note_btn):
                base = _strip_to_base(it.get("text", "") or "")
                if not base:
                    show_toast(self,
                               "Type a client name first to add a note.",
                               kind="info")
                    return
                self._open_apa_note_dialog(base, sec, refresh)

            note_btn.config(command=_open_note_dialog)
            _refresh_note_btn()
            attach_tooltip(
                note_btn,
                "Add a note that's appended to the Teams message for this "
                f"{section_name.lower()} (not saved to the audit doc)")

        # Trello card button — every job row in every section gets one.
        # Click jumps to the first pinned card (or opens the multi-select
        # picker when no pin exists). Previously gated to Final/Initial/
        # Daily Upload sections only; the gate hid the affordance on
        # ~75% of rows even though every job in APA has a card. Pins are
        # canonicalized across the suite (see project_trello_pin_
        # canonicalization), so a pin set here shows up in audit /
        # snapshot / job-notes too.
        init_base = _strip_to_base(item.get("text", "")) if item.get("text") else ""
        init_count = (len(persistence.get_trello_card_ids(init_base))
                      if init_base else 0)
        trello_btn = tk.Button(
            row,
            text=f"📌 {init_count}" if init_count else "📌",
            font=("Segoe UI Variable", 8 if init_count else 9,
                  "bold" if init_count else "normal"),
            bg=row_bg,
            fg=GREEN_DARK if init_count else "#888888",
            activebackground=row_bg,
            relief="flat", padx=2, cursor="hand2")
        trello_btn.pack(side="right", padx=(0, 2))
        bg_tracked.append(trello_btn)
        attach_tooltip(
            trello_btn,
            lambda it=item: (
                lambda base=_strip_to_base(it.get("text") or ""): (
                    f"{len(persistence.get_trello_card_ids(base))} Trello "
                    "card(s) pinned — click to open the first one"
                    if base and persistence.get_trello_card_ids(base)
                    else ("Pin a Trello card to this job" if base
                          else "Type a client name first to pin a card"))
            )())

        def _refresh_trello_btn(it=item, b=trello_btn):
            base = _strip_to_base(it.get("text", "")) if it.get("text") else ""
            count = len(persistence.get_trello_card_ids(base)) if base else 0
            try:
                if count:
                    b.config(text=f"📌 {count}",
                             fg=GREEN_DARK,
                             font=("Segoe UI Variable", 8, "bold"))
                else:
                    b.config(text="📌", fg=TEXT_MUTED,
                             font=("Segoe UI Variable", 9))
            except tk.TclError:
                pass

        def _open_trello(it=item, refresh=_refresh_trello_btn):
            base = _strip_to_base(it.get("text", "")) if it.get("text") else ""
            if not base:
                show_toast(self,
                           "Type a client name first", kind="info")
                return
            pinned = persistence.get_trello_card_ids(base)
            if pinned:
                # Open the FIRST pinned card — multi-card navigation
                # lives in Job Notes.
                try:
                    import webbrowser
                    webbrowser.open(f"https://trello.com/c/{pinned[0]}")
                except Exception:
                    pass
                return
            # No pin — open the picker so the user can link one.
            from job_widgets import open_trello_pin_dialog
            open_trello_pin_dialog(
                self, base,
                on_pinned=lambda _ids: refresh())

        trello_btn.config(command=_open_trello)

        # Franchise tag badge (UI-only, never written to .docx). Renders as
        # a colored pill showing the current tag (or 🏢 when unset). Click
        # opens a small popup with the franchise list + Manage… option.
        fr_btn = tk.Button(row, font=("Segoe UI Variable", 8, "bold"),
                            relief="flat", bd=0, padx=6, pady=0,
                            cursor="hand2")
        fr_btn.pack(side="left", padx=(2, 4))
        attach_tooltip(
            fr_btn,
            lambda it=item: (f"Franchise: {it.get('franchise')} "
                             "(click to change)"
                             if it.get("franchise")
                             else "Tag the franchise for this job"))
        # NOT in bg_tracked: a tagged badge keeps its franchise color even
        # when the row goes yellow for pending status. The refresher below
        # is called from _ssync via the row_bg holder so untagged badges
        # still track row color.
        row_bg_holder = [row_bg]

        def _refresh_fr_btn():
            label = item.get("franchise", "")
            if label:
                bg, fg = _franchise_colors(label)
                fr_btn.config(text=label, bg=bg, fg=fg, activebackground=bg)
            else:
                cur_bg = row_bg_holder[0]
                fr_btn.config(text="🏢", bg=cur_bg, fg=TEXT_MUTED,
                              activebackground=cur_bg)
        _refresh_fr_btn()

        def _open_fr_menu(it=item, btn=fr_btn, refresh=_refresh_fr_btn):
            menu = tk.Menu(self, tearoff=0)
            franchises = persistence.get_franchise_list()
            current = it.get("franchise", "")
            if current:
                menu.add_command(label="✓ (current)  " + current, state="disabled")
                menu.add_separator()
            menu.add_command(label="(none)",
                             command=lambda: self._set_item_franchise(it, "", refresh))
            for fr in franchises:
                menu.add_command(label=fr,
                                  command=lambda f=fr: self._set_item_franchise(it, f, refresh))
            menu.add_separator()
            menu.add_command(label="Manage franchises…",
                              command=lambda: self._open_franchise_manager(refresh))
            try:
                x = btn.winfo_rootx()
                y = btn.winfo_rooty() + btn.winfo_height()
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()
        fr_btn.config(command=_open_fr_menu)

        # Client / carrier text entry. Was ttk.Combobox with auto-
        # Post(popdown) on typing; that path is unusable because
        # ttk::combobox::Post installs a Tk grab on the popdown listbox
        # which steals keystrokes from the entry no matter how we try
        # to release it — four iterations of fixes (grab-release, focus-
        # reclaim, FocusOut tracking, Unmap binding, grab-release-on-
        # popdown-path) all left a follow-on bug. Replaced with a plain
        # ttk.Entry plus a custom typeahead popup (tk.Toplevel +
        # Listbox) that doesn't grab anything. Focus stays in the entry
        # the whole time the user types; the popup just shows
        # filtered suggestions and accepts clicks/Return to pick.
        text_var = tk.StringVar(value=item.get("text", ""))
        entry = ttk.Entry(row, textvariable=text_var,
                            font=("Segoe UI Variable", 9))
        entry.pack(side="left", fill="x", expand=True, padx=(2, 4))

        _popup = {"top": None, "lb": None, "scroll_unbind_id": None}

        def _ensure_popup(e=entry, full=self._known_clients):
            """Lazy-create the popup Toplevel + Listbox. Returns the
            (toplevel, listbox) pair."""
            if _popup["top"] is not None:
                return _popup["top"], _popup["lb"]
            try:
                top = e.winfo_toplevel()
                pw = tk.Toplevel(top)
                pw.wm_overrideredirect(True)
                pw.withdraw()
                pw.configure(bg=BORDER)
                lb = tk.Listbox(
                    pw, height=8,
                    font=("Segoe UI Variable", 9),
                    bg=WHITE, fg=TEXT_DARK,
                    selectbackground=GREEN_LIGHT,
                    selectforeground=TEXT_DARK,
                    relief="flat", bd=0,
                    exportselection=False,
                    activestyle="dotbox",
                    highlightthickness=0)
                lb.pack(fill="both", expand=True, padx=1, pady=1)
            except tk.TclError:
                return None, None
            _popup["top"] = pw
            _popup["lb"] = lb

            def _pick(_e=None, v=text_var, ent=entry):
                sel = lb.curselection()
                if sel:
                    val = lb.get(sel[0])
                    v.set(val)
                    try:
                        ent.icursor("end")
                    except tk.TclError:
                        pass
                _hide()
                try:
                    ent.focus_set()
                except tk.TclError:
                    pass

            lb.bind("<Button-1>", lambda _e: lb.after(1, _pick))
            lb.bind("<Return>", _pick)
            return pw, lb

        def _hide(_=None):
            pw = _popup.get("top")
            if pw is not None:
                try:
                    pw.withdraw()
                except tk.TclError:
                    pass

        def _show_with(values, e=entry):
            pw, lb = _ensure_popup()
            if pw is None or lb is None:
                return
            if not values:
                _hide()
                return
            try:
                lb.delete(0, "end")
                for s in values[:50]:
                    lb.insert("end", s)
                # Pre-select the first match so Return picks it.
                lb.selection_clear(0, "end")
                lb.selection_set(0)
                lb.activate(0)
                e.update_idletasks()
                x = e.winfo_rootx()
                y = e.winfo_rooty() + e.winfo_height()
                w = max(e.winfo_width(), 240)
                rows_shown = min(len(values), 8)
                h = rows_shown * 18 + 6
                pw.geometry(f"{w}x{h}+{x}+{y}")
                pw.deiconify()
                pw.lift()
            except tk.TclError:
                pass

        def _filter_dropdown(event, e=entry, v=text_var,
                              full=self._known_clients):
            if event.keysym == "Escape":
                _hide()
                return
            if event.keysym == "Down":
                # Pop and let user navigate via listbox keys; we don't
                # forward keys into the listbox to avoid grab issues.
                # User can click the highlighted row.
                return
            if event.keysym == "Return":
                # Pick the currently highlighted suggestion if popup
                # is visible AND user hasn't fully typed a unique name.
                pw, lb = _popup.get("top"), _popup.get("lb")
                if pw is not None and lb is not None:
                    try:
                        if str(pw.state()) != "withdrawn":
                            sel = lb.curselection()
                            if sel:
                                val = lb.get(sel[0])
                                v.set(val)
                                try:
                                    e.icursor("end")
                                except tk.TclError:
                                    pass
                                _hide()
                                return
                    except tk.TclError:
                        pass
                return
            if event.keysym in (
                    "Up", "Tab", "Left", "Right",
                    "Shift_L", "Shift_R", "Control_L", "Control_R",
                    "Alt_L", "Alt_R", "Caps_Lock", "Win_L", "Win_R"):
                return
            typed = (v.get() or "").strip().lower()
            if not typed:
                _hide()
                return
            prefix, sub = [], []
            for s in full:
                sl = s.lower()
                if sl.startswith(typed):
                    prefix.append(s)
                elif typed in sl:
                    sub.append(s)
            _show_with(prefix + sub)

        entry.bind("<KeyRelease>", _filter_dropdown)
        # Hide the popup when the user clicks elsewhere or tabs away.
        # 150ms delay so a click ON the popup's listbox can pick a value
        # before the popup hides.
        entry.bind("<FocusOut>",
                    lambda _e=None: entry.after(150, _hide), add="+")
        entry.bind("<Escape>", _hide, add="+")
        # Clean up the popup if the row is destroyed (re-render path).
        entry.bind("<Destroy>", lambda _e=None: _hide(), add="+")
        # Forward-ref holder for the recurring-extension badge refresh —
        # the function is defined later in this method (it needs st_cb),
        # but _tsync runs on every keystroke and must repaint the badge
        # when the user edits the client text (the badge is keyed by
        # franchise_key(text)). Holder gets filled in below.
        _ext_refresh_holder = [None]
        # Audit-row note button indicator is keyed by canonical client name;
        # rebind on every edit so the green dot follows inline rename.
        _note_refresh = (_refresh_note_btn
                          if section_name in AUDIT_SECTIONS and note_btn is not None
                          else None)
        def _tsync(*_, it=item, v=text_var, sec=section_name,
                   refresh=_refresh_fr_btn,
                   refresh_trello=(_refresh_trello_btn
                                   if trello_btn is not None else None),
                   ext_holder=_ext_refresh_holder,
                   refresh_note=_note_refresh):
            had = bool(it["text"].strip())
            it["text"] = v.get()
            self._mark_dirty()
            # Count label only changes when blank↔non-blank crosses over
            if had != bool(it["text"].strip()):
                self._refresh_count_label(sec)
            # Re-resolve the franchise tag from the new client key.
            # Only auto-apply when persistence HAS a tag for the new key —
            # never auto-clear an explicit franchise just because the user
            # is mid-typing or editing the client text. (Old behavior wiped
            # the badge on every keystroke when no saved tag existed yet,
            # which is why "the franchise sometimes doesn't save".)
            try:
                tag = persistence.get_franchise_tags().get(
                    _franchise_key(it["text"]), "")
                if tag and tag != it.get("franchise", ""):
                    it["franchise"] = tag
                    refresh()
            except Exception:
                pass
            # Trello pin badge tracks the new client name — without this
            # an editable row would still show the prior client's count
            # until the panel was closed and reopened.
            if refresh_trello is not None:
                refresh_trello()
            # Recurring-extension badge follows the franchise key too.
            if ext_holder[0] is not None:
                try:
                    ext_holder[0]()
                except Exception:
                    pass
            if refresh_note is not None:
                try:
                    refresh_note()
                except Exception:
                    pass
        text_var.trace_add("write", _tsync)

        # Sub dropdown — only shown in sections that use one
        sub_opts = _sub_options_for_section(section_name)
        sub_var = None  # captured by autofill closure below
        if sub_opts is not None:
            sub_var = tk.StringVar(value=item.get("sub", ""))
            sub_cb  = ttk.Combobox(row, textvariable=sub_var,
                                   values=sub_opts, width=18,
                                   font=("Segoe UI Variable", 9),
                                   state=("readonly"
                                          if section_name in AUDIT_SECTIONS
                                          else "normal"))
            sub_cb.pack(side="left", padx=(2, 4))
            def _sub_sync(*_, it=item, v=sub_var, sec=section_name,
                          btn=msg_btn):
                it["sub"] = v.get()
                self._mark_dirty()
                # In audit sections, show 💬 only once a sub is picked
                if sec in AUDIT_SECTIONS and btn is not None:
                    try:
                        if it["sub"].strip():
                            btn.pack(side="right", padx=(0, 2))
                        else:
                            btn.pack_forget()
                    except tk.TclError:
                        pass
            sub_var.trace_add("write", _sub_sync)

        # Status dropdown — swap options for audit sections
        status_opts = _status_options_for_section(section_name)
        status_var  = tk.StringVar(value=item.get("status", ""))
        st_cb = ttk.Combobox(row, textvariable=status_var,
                              values=status_opts, width=14,
                              font=("Segoe UI Variable", 9), state="readonly")
        st_cb.pack(side="left", padx=(2, 4))

        # 🔁 Recurring-extension badge. Shown when the user has flipped
        # this client's status to "extended" 2+ times across all APA
        # sessions — a signal the job keeps coming back instead of
        # closing out. Persists in state.json via
        # persistence.bump_apa_extended, keyed off the same canonical
        # client key the franchise tag uses so multi-day reads land on
        # the same counter. Mirrors the audit panel's recurring badge.
        ext_badge = tk.Label(
            row, text="", font=("Segoe UI Variable", 8, "bold"),
            bg=row_bg, fg=WARN_FG, padx=4, pady=0)
        bg_tracked.append(ext_badge)

        # Filled into the holder below so _tsync (client text edits)
        # can repaint the badge as the franchise key changes.
        def _refresh_ext_badge(it=item, lbl=ext_badge, bg_h=row_bg_holder):
            try:
                key = _franchise_key(it.get("text", "") or "")
                cnt = persistence.get_apa_extended_count(key) if key else 0
            except Exception:
                cnt = 0
            try:
                if cnt >= 2:
                    lbl.config(text=f" 🔁 {cnt}× extended ",
                                bg=WARN_BG, fg=WARN_FG)
                    # Pack to the LEFT of the status combobox so it sits
                    # in line of sight when the user is scanning status
                    # values; idempotent — re-pack is a no-op when
                    # already mapped.
                    try:
                        lbl.pack(side="left", padx=(2, 0),
                                  before=st_cb)
                    except tk.TclError:
                        pass
                    try:
                        from tool_panel import attach_tooltip
                        hist = (
                            persistence.get_apa_extended_history()
                                       .get(key, {}) or {})
                        dates = hist.get("dates") or []
                        tip = (f"Set to 'extended' {cnt} times.\n"
                                f"Last: {dates[-1]}" if dates else
                                f"Set to 'extended' {cnt} times.")
                        attach_tooltip(lbl, tip)
                    except Exception:
                        pass
                else:
                    try:
                        lbl.pack_forget()
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass
        _refresh_ext_badge()
        _ext_refresh_holder[0] = _refresh_ext_badge

        # Status change: update bg in place — no full re-render, no scroll jump
        def _ssync(*_, it=item, v=status_var, tracked=bg_tracked,
                   sec=section_name, row_bg_h=row_bg_holder,
                   refresh_fr=_refresh_fr_btn,
                   refresh_ext=_refresh_ext_badge):
            had = bool(it.get("status", ""))
            had_extended = (it.get("status") or "").lower() == "extended"
            new_status = v.get()
            it["status"] = new_status
            self._mark_dirty()
            # First time the user transitions this row TO "extended"
            # in this status change, bump the recurring counter so the
            # badge tracks repeat extensions across days. Going FROM
            # extended → other (or extended → extended via no-op write)
            # doesn't bump, so the count strictly reflects "how many
            # times did I have to extend this."
            new_is_extended = (new_status or "").lower() == "extended"
            if new_is_extended and not had_extended:
                try:
                    key = _franchise_key(it.get("text", "") or "")
                    if key:
                        persistence.bump_apa_extended(key)
                except Exception:
                    pass
                try:
                    refresh_ext()
                except Exception:
                    pass
            new_bg = _bg_for(v.get())
            row_bg_h[0] = new_bg
            for w in tracked:
                try:
                    w.configure(bg=new_bg, activebackground=new_bg)
                except tk.TclError:
                    try:
                        w.configure(bg=new_bg)
                    except tk.TclError:
                        pass
            # Untagged franchise button tracks row_bg; tagged keeps its color.
            refresh_fr()
            if had != bool(it["status"]):
                self._refresh_count_label(sec)
        status_var.trace_add("write", _ssync)

        # ✨ Autofill from Trello — only-fill-empty: looks at the pinned
        # card (or fuzzy-matches by client name), then fills the carrier
        # suffix into `text`, the lane name into `sub`, and a label-derived
        # value into `status` ONLY for fields the user hasn't already set.
        # Placed left of 📌 so the right-side cluster reads ✨ 📌 💬 ×.
        spark_btn = tk.Button(
            row, text="✨", font=("Segoe UI Variable", 9),
            bg=row_bg, fg=TEXT_MUTED, activebackground=row_bg,
            relief="flat", padx=2, cursor="hand2")
        spark_btn.pack(side="right", padx=(0, 2))
        bg_tracked.append(spark_btn)

        def _autofill(it=item, sec=section_name,
                      tv=text_var, sv=sub_var, stv=status_var,
                      sopts=sub_opts):
            self._autofill_row_from_trello(
                item=it, section_name=sec,
                text_var=tv, sub_var=sv, status_var=stv,
                sub_opts=sopts)
        spark_btn.config(command=_autofill)

        # Right-click anywhere on the row → shared client context menu
        # (Pin to Trello, Change folder, Edit aliases, Reset memory) —
        # same surface as Audit / IUQ / Snapshot / Hygiene. Client name
        # is resolved FRESH at click time via `_strip_to_base(item.text)`
        # so the user's inline text edits aren't captured as a stale
        # client at bind time.
        def _show_row_menu(event, it=item):
            from job_widgets import show_card_context_menu_at_event
            import config as _cfg
            base = _strip_to_base(it.get("text", "") or "")
            if not base:
                show_toast(
                    self,
                    "Type a client name first to use the row menu.",
                    kind="info")
                return
            try:
                ab = (_cfg.load().get("audit_base") or "") or None
            except Exception:
                ab = None
            show_card_context_menu_at_event(
                event, self, base, audit_base=ab)
        # Bindtag walk so right-click reaches every descendant of the
        # row (combobox listboxes, sub buttons, etc.). Same pattern
        # `attach_card_context_menu` uses — one binding total, no per-
        # widget re-binding when state changes.
        _ctr = getattr(self, "_apa_menu_counter", 0) + 1
        self._apa_menu_counter = _ctr
        _tag = f"_apa_rowmenu_{_ctr}"
        try:
            row.bind_class(_tag, "<Button-3>", _show_row_menu)
        except tk.TclError:
            _tag = None
        if _tag:
            def _walk(w, tag=_tag):
                try:
                    bt = w.bindtags()
                    if tag not in bt:
                        w.bindtags(bt + (tag,))
                except tk.TclError:
                    return
                for child in w.winfo_children():
                    _walk(child)
            _walk(row)


def main(argv=None):
    # run_standalone honors APAMonitorApp.TOOL_GEOMETRY_KEY automatically.
    run_standalone(APAMonitorApp, geometry="780x780", minsize=(620, 500))


if __name__ == "__main__":
    main()
