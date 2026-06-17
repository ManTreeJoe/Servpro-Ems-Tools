import tkinter as tk
from tkinter import ttk, messagebox
import pdfrw
import os
import re
import threading
import zipfile
import webbrowser
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle)

import audit_export as _audit_export
import audit_logic
import config
import ctk_helpers as ctkh
import paths
import persistence
from job_widgets import (CommercialToggle, render_memory_pin,
                         attach_card_context_menu,
                         open_trello_pin_dialog)
from tool_panel import (ToolPanel, run_standalone, show_toast, ScrollableFrame,
                         attach_rich_tooltip)
from ui_buttons import link_button
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    TEXT_MUTED, BORDER, FLAG_RED, SURFACE_2,
                    NEUTRAL_HOVER,
                    SUCCESS_BG, SUCCESS_FG,
                    INFO_BG, INFO_HOVER, INFO_FG,
                    LINK_BG, LINK_HOVER, LINK_FG,
                    WARN_BG, WARN_HOVER, WARN_FG,
                    DANGER_FG, ON_ACCENT)
from audit_logic import (
    is_commercial_form as _is_commercial_form,
    biz_days_since as _biz_days_since,
    persist_key, find_docs_dir,
    _has_files,
    DOCUSKETCH_RE,
)
# Reuse run_audit_gui's WC import constants + helpers so the Snapshot
# audit drops files in the same place + uses the same multi-part /
# stage-folder routing rules. Local import (not at module top) avoids
# yanking the audit GUI's heavy imports into snapshot_gui's startup
# critical path; the module gets loaded the first time a user clicks
# the WC button.

_CFG       = config.load()
TEMPLATE   = _CFG["snapshot_template"]
OUTPUT_DIR = _CFG["snapshot_output"]

# Snapshot parsing + PDF logic now lives in the UI-free snapshot_logic
# module (shared with snapshot_web, audit_web, scope_dialog). Re-export every
# name so the Tk SnapshotApp + other importers are unaffected. See
# EMS_Tk_Extraction_Plan.md.
from snapshot_logic import (  # noqa: E402,F401
    get_weekday, fmt_techs, detect_first_visit,
    apply_snapshot_field_rules, _align_date_to_weekday,
    _split_email_blocks, _extract_email_block_subs, _is_no_answer,
    parse_comments, parse_scope, _RoomTable, build_scope_pdf,
    fill_pdf, append_overflow_pages,
    SNAPSHOT_TEMPLATE_SUBS_MAX, SNAPSHOT_TEMPLATE_LOGS_MAX,
)


AUDIT_BASE    = _CFG["audit_base"]
AUDIT_TYPES   = ["CONTENTS", "EMS", "RECON"]
AUDIT_SUBDIRS = ["DOCS", "PICS", "FIELD DOCS"]

DOWNLOADS     = os.path.join(os.environ["USERPROFILE"], "Downloads")



def _missing_subdirs_for(cp):
    """Return the list of CONTENTS/EMS/RECON empty-subfolder paths for a
    job. Snapshot-specific check that the regular Run Audit doesn't do
    — a snapshot is filed at handoff time and the user wants a quick
    visual on which subfolders still need photos/docs dropped in."""
    if not cp or not os.path.isdir(cp):
        return []
    return [
        f"{jt}\\{sub}"
        for jt in AUDIT_TYPES
        for sub in AUDIT_SUBDIRS
        if os.path.isdir(os.path.join(cp, jt))
        and not _has_files(os.path.join(cp, jt, sub))
    ]


def run_audit(year=None, current_insured=None, current_log_rows=None,
              current_carrier=None, progress_cb=None,
              folder_override=None):
    """Audit one job (or sweep all current-year jobs when current_insured
    is None). Delegates to audit_logic.audit_jobs so the backend matches
    the daily Run Audit panel — same form/photo checks, same dispute /
    rejection detection, same audit cache, same SharePoint enrichment.

    Returns the same result shape as the Run Audit, plus snapshot-only
    extras: `is_current` (True for the matched insured) and `missing`
    (CONTENTS/EMS/RECON empty-subdir list).
    """
    from audit_logic import audit_jobs as _audit_jobs_core

    current_year = year or datetime.today().year
    if not os.path.exists(AUDIT_BASE):
        return None, "Cannot reach X: drive — is it connected?"

    def _find_year_folder(y):
        return next(
            (os.path.join(AUDIT_BASE, d) for d in os.listdir(AUDIT_BASE)
             if os.path.isdir(os.path.join(AUDIT_BASE, d)) and str(y) in d
             and not ("LA" in d.upper() and "FIRE" in d.upper())),
            None)

    # Compose a `raw` line from the snapshot's log entries so audit_logic's
    # dispute/rejection detection sees any wording typed into the activity
    # column. Empty rows are skipped — joining "" lines would just create
    # blank lines that detect_dispute_notes correctly ignores anyway, but
    # building the raw cleanly is easier to reason about.
    def _raw_from_logs():
        if not current_log_rows:
            return None
        parts = []
        for row in current_log_rows:
            try:
                date, weekday, activity, techs = row
            except (TypeError, ValueError):
                continue
            line = " ".join(str(x).strip() for x in (date, weekday, activity, techs)
                            if str(x).strip())
            if line:
                parts.append(line)
        return "\n".join(parts) if parts else None

    raw = _raw_from_logs()
    snapshot_run_date = datetime.today().strftime("%m-%d-%Y")

    # Single-job mode: hand audit_logic a 1-element list. The caller
    # supplies a name pattern (could be partial) — audit_logic does the
    # year-folder search and reversed-name fallback the same way.
    if current_insured:
        jobs = [{"client": current_insured, "raw": raw}]
        # Build the override-aware lookup via the shared helper so the
        # behavior matches Run Audit's Audit-One-Job path.
        from audit_logic import make_folder_lookup
        _lookup = make_folder_lookup(folder_override, current_insured)
        results, err = _audit_jobs_core(
            jobs, AUDIT_BASE, year=current_year,
            folder_path_lookup=_lookup,
            run_date=snapshot_run_date,
            progress_cb=progress_cb,
        )
        if err:
            return results, err
        if not results:
            return None, (
                f"No folder found matching '{current_insured}' in "
                f"{current_year} or {current_year - 1}")
        # Single-job audit returns one row (or a not-found row). Stamp
        # is_current and fold in the snapshot's missing-subdir check.
        for r in results:
            if not r.get("found"):
                return None, (
                    f"No folder found matching '{current_insured}' in "
                    f"{current_year} or {current_year - 1}")
            r["is_current"] = True
            r["missing"]    = _missing_subdirs_for(r.get("path"))
            if r["missing"]:
                r["flagged"] = True
        return results, None

    # Full sweep — list every client folder in the current year and feed
    # them all through audit_logic. Snapshot's "Audit only" button uses
    # this path. None of these are the "current" job (no insured set).
    year_folder = _find_year_folder(current_year)
    if not year_folder:
        return None, f"No {current_year} folder found in X:\\IE_Public"
    try:
        all_clients = sorted(os.listdir(year_folder))
    except OSError as ex:
        return None, f"Could not list {year_folder}: {ex}"
    jobs = [{"client": c, "raw": raw} for c in all_clients]
    results, err = _audit_jobs_core(
        jobs, AUDIT_BASE, year=current_year,
        folder_path_lookup=persistence.get_folder_path,
        run_date=snapshot_run_date,
    )
    if results:
        for r in results:
            r["is_current"] = False
            r["missing"]    = _missing_subdirs_for(r.get("path"))
            if r["missing"]:
                r["flagged"] = True
    return results, err

def _add_trello_toggle(card, notes):
    """Attach a collapsible Trello Notes section to an audit card (current job only)."""
    if not notes or not notes.strip():
        return
    state    = [False]
    bg_white = "#FFFFFF"

    toggle_row = tk.Frame(card, bg=bg_white)
    toggle_row.pack(fill="x", padx=10, pady=(0, 4))
    tk.Frame(toggle_row, bg=BORDER, height=1).pack(fill="x", pady=(0, 3))

    txt_widget = tk.Text(card, height=7, font=("Consolas", 7),
                         bg=SURFACE_2, fg=TEXT_GRAY, wrap="word",
                         relief="flat", borderwidth=0, state="normal")
    txt_widget.insert("1.0", notes.strip())
    txt_widget.config(state="disabled")

    def _toggle_notes():
        state[0] = not state[0]
        if state[0]:
            btn.config(text="▼ Trello Notes")
            txt_widget.pack(fill="x", padx=10, pady=(0, 6))
        else:
            btn.config(text="▶ Trello Notes")
            txt_widget.pack_forget()

    btn = tk.Button(toggle_row, text="▶ Trello Notes",
                    font=("Segoe UI Variable", 7, "bold"), bg=bg_white, fg=TEXT_GRAY,
                    relief="flat", cursor="hand2", anchor="w", padx=0, pady=0,
                    command=_toggle_notes)
    btn.pack(side="left")


_ICON = paths.resource("wrench.ico")


class SnapshotApp(ToolPanel):
    TOOL_TITLE = "EMS Snapshot"
    TOOL_AUMID = "Servpro.EMS.Snapshot"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("EMS Snapshot")
        self.geometry("740x640")
        self.configure(bg=BG)
        self.resizable(True, True)
        if os.path.isfile(_ICON):
            try:
                self.iconbitmap(_ICON)
            except Exception:
                pass

        self.sub_entries  = []
        self.log_entries  = []
        self.first_visit  = ""
        self.insured = self.carrier = self.dol = self.cause = ""
        # Commercial-job extra: when set, the PDF "Insured / Job" header
        # renders as "<self.insured> — <self._customer_for_header>" so
        # both the business name AND the contact person show. Lookups
        # (folder, filename, pin) keep using self.insured alone.
        self._customer_for_header = ""
        self._drag_data   = None
        self._scope_rooms = []

        self._build_header()
        self._build_lifecycle_banner()
        self._build_input_frame()
        self._build_preview_frame()
        self._build_audit_frame()

        self.frame_preview.pack_forget()
        self.frame_audit.pack_forget()

    # ── Lifecycle banner ─────────────────────────────────────────────────────
    def _build_lifecycle_banner(self):
        """Slim green strip reinforcing that Snapshot is the CLOSEOUT
        step in a file's life. Drawn under the header so it's visible
        on every step (input / preview / audit) without redrawing per
        step. Always rendered — embedded or standalone — since the
        lifecycle cue is independent of the chrome above it."""
        banner = tk.Label(
            self,
            text="🏁  CLOSEOUT  ·  Generate handoff PDF + final audit",
            font=("Segoe UI Variable", 9, "bold"),
            bg=SUCCESS_BG, fg=SUCCESS_FG,
            anchor="w", padx=14, pady=4)
        banner.pack(fill="x", side="top")

    # ── Navigation guard ──────────────────────────────────────────────────────
    def on_hide(self):
        """Warn before navigating away from a snapshot mid-workflow."""
        try:
            if self.frame_preview.winfo_ismapped():
                from tkinter import messagebox as _mb
                return bool(_mb.askyesno(
                    "Snapshot in progress",
                    "You're partway through a snapshot. Discard and switch tools?",
                    parent=self))
        except Exception:
            pass
        return True

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        self.header = ctkh.ctk.CTkFrame(self, fg_color=GREEN,
                                        corner_radius=0, height=44)
        self.header.pack_propagate(False)
        self.header_label = ctkh.ctk.CTkLabel(
            self.header, text="EMS Snapshot",
            font=ctkh.font(14, "bold"), text_color=WHITE)
        self.header_label.pack(pady=10)
        # Skip the green band when embedded; launcher already shows the title.
        # Per-step text updates flow through _set_step_title which also pushes
        # to self.title() so the launcher header reflects the current step.
        if not self._embedded:
            self.header.pack(fill="x")

    def _set_step_title(self, text):
        try:
            self.header_label.configure(text=text)
        except tk.TclError:
            pass
        self.title(text)

    # ── Step 1: Input ─────────────────────────────────────────────────────────
    def _build_input_frame(self):
        self.frame_input = tk.Frame(self, bg=BG)
        self.frame_input.pack(fill="both", expand=True)

        form = tk.Frame(self.frame_input, bg=BG, padx=20, pady=10)
        form.pack(fill="x")

        labels = ["Insured / Job", "Carrier / Claim #",
                  "Date of Loss", "Cause / Category / Class"]
        self._entries     = []
        self._form_labels = []
        for lbl in labels:
            wlbl = ctkh.h2(form, lbl, fg_color=BG)
            self._form_labels.append(wlbl)
            e = ctkh.entry(form, width=320)
            self._entries.append(e)
        self.e_insured, self.e_carrier, self.e_dol, self.e_cause = self._entries

        # First-site row — always full-width footer below the 4 entries
        self._fsv_label_a = ctkh.h2(form, "First Site Visit", fg_color=BG)
        self._fsv_label_b = ctkh.ctk.CTkLabel(
            form, text="Auto-detected from comments",
            font=ctkh.font(9), text_color=TEXT_GRAY, fg_color=BG)

        # Responsive grid layout — 2x2 when wide, 4x1 when narrow.
        self._form_paired   = None
        self._form_after_id = None
        def _layout_form(_e=None):
            # Bail entirely if `form` or any of the widgets we'd touch
            # have been destroyed — happens when the user navigates
            # away from the snapshot tool while a pending after()
            # is still queued ("bad window path name" otherwise). Every
            # widget access inside is wrapped because Tk teardown
            # destroys children in arbitrary order — `form` can still
            # exist while a label inside it is already gone.
            try:
                if not form.winfo_exists():
                    return
                w = form.winfo_width()
                if w <= 1:
                    return
                want_paired = w >= 820
                if want_paired == self._form_paired:
                    return
                for wgt in (self._form_labels + self._entries +
                            [self._fsv_label_a, self._fsv_label_b]):
                    try: wgt.grid_forget()
                    except Exception: pass
                if want_paired:
                    # Pair into two columns: (Insured, Carrier) | (DOL, Cause)
                    pairs = [(0, 1), (2, 3)]
                    for r, (a, b) in enumerate(pairs):
                        self._form_labels[a].grid(row=r, column=0, sticky="w", pady=3)
                        self._entries[a].grid(row=r, column=1, sticky="ew",
                                                padx=10, pady=3)
                        self._form_labels[b].grid(row=r, column=2, sticky="w",
                                                    padx=(20, 0), pady=3)
                        self._entries[b].grid(row=r, column=3, sticky="ew",
                                                padx=10, pady=3)
                    self._fsv_label_a.grid(row=2, column=0, sticky="w", pady=3)
                    self._fsv_label_b.grid(row=2, column=1, columnspan=3,
                                            sticky="w", padx=10)
                    form.columnconfigure(1, weight=1)
                    form.columnconfigure(3, weight=1)
                    form.columnconfigure(0, weight=0)
                    form.columnconfigure(2, weight=0)
                else:
                    # Stack 4 deep, label/entry per row.
                    for i, (lbl_w, ent_w) in enumerate(zip(self._form_labels,
                                                           self._entries)):
                        lbl_w.grid(row=i, column=0, sticky="w", pady=3)
                        ent_w.grid(row=i, column=1, sticky="ew", padx=10, pady=3)
                    self._fsv_label_a.grid(row=4, column=0, sticky="w", pady=3)
                    self._fsv_label_b.grid(row=4, column=1, sticky="w", padx=10)
                    form.columnconfigure(1, weight=1)
                    form.columnconfigure(0, weight=0)
                    # No col 2/3 in narrow mode — clear any prior weight.
                    form.columnconfigure(2, weight=0)
                    form.columnconfigure(3, weight=0)
                self._form_paired = want_paired
            except tk.TclError:
                # Any widget in the chain got destroyed mid-layout —
                # bail. The panel is going away; let it.
                return
        def _on_form_configure(_e=None):
            # Configure events can fire mid-teardown (window resize as
            # the user closes). after_cancel + after both need a live
            # `self` — swallow TclError on either.
            try:
                if self._form_after_id is not None:
                    try: self.after_cancel(self._form_after_id)
                    except Exception: pass
                self._form_after_id = self.after(40, _layout_form)
            except tk.TclError:
                pass
        form.bind("<Configure>", _on_form_configure, add="+")
        # Apply initial layout once the panel has real geometry.
        try:
            self.after(50, _layout_form)
        except tk.TclError:
            pass

        # Auto-pull row — fetches cards currently in the ESTIMATING /
        # SNAPSHOT lane and pre-fills every form field + the comments
        # box from the chosen card. Saves the manual paste step entirely
        # for the common case where the snapshot was queued via Trello.
        pull_row = tk.Frame(self.frame_input, bg=BG, padx=20)
        pull_row.pack(fill="x", pady=(4, 0))
        tk.Button(pull_row, text="📥 Pull from Trello SNAPSHOT lane",
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=GREEN, fg=WHITE,
                  activebackground=GREEN_DARK, activeforeground=WHITE,
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=self._open_snapshot_picker).pack(side="left")
        # Search-any-card escape hatch — sometimes the job's card isn't
        # in the SNAPSHOT lane yet (still in monitoring, recon, etc.)
        # but the user wants to snapshot it anyway. This searches every
        # in-scope board by name and fills the form from whatever they
        # pick — same downstream code path as the lane picker.
        tk.Button(pull_row, text="🔎 Find any card…",
                  font=("Segoe UI Variable", 9),
                  bg=WHITE, fg=TEXT_DARK,
                  activebackground=NEUTRAL_HOVER, activeforeground=TEXT_DARK,
                  relief="solid", bd=1, padx=12, pady=6, cursor="hand2",
                  command=self._open_any_card_picker
                  ).pack(side="left", padx=(8, 0))
        tk.Label(pull_row,
                 text="Or paste comments below as before",
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY
                 ).pack(side="left", padx=(12, 0))

        ctkh.h2(self.frame_input, "Paste Trello Comments Below").pack(
            anchor="w", padx=20, pady=(8, 2))

        # Pack the button row to the BOTTOM first so it claims its space before
        # the expanding text area consumes the rest. Otherwise on short windows
        # the buttons get pushed off-screen.
        # "Audit Only" was removed — it just forwarded to Run Audit's
        # "🔍 Audit One Job" with no Snapshot-specific behavior. Users
        # who want audit-only switch to Run Audit on the toolstrip.
        btn_row = tk.Frame(self.frame_input, bg=BG)
        btn_row.pack(side="bottom", fill="x", padx=20, pady=12)
        ctkh.btn(btn_row, "Parse & Preview  →",
                 command=self._parse_and_preview,
                 kind="primary", height=40
                 ).pack(fill="x", expand=True)

        txt_frame = tk.Frame(self.frame_input, padx=20)
        txt_frame.pack(fill="both", expand=True)
        sb = tk.Scrollbar(txt_frame)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(sb)
        except Exception:
            pass
        sb.pack(side="right", fill="y")
        self.txt_comments = tk.Text(txt_frame, height=8, font=("Consolas", 9),
                                     yscrollcommand=sb.set, wrap="word")
        self.txt_comments.pack(fill="both", expand=True)
        sb.config(command=self.txt_comments.yview)

    # ── Step 2: Preview / Edit ────────────────────────────────────────────────
    def _build_preview_frame(self):
        self.frame_preview = tk.Frame(self, bg=BG)
        self.frame_preview.pack(fill="both", expand=True)

        # Nav bar
        nav = tk.Frame(self.frame_preview, bg=BG, padx=20, pady=6)
        nav.pack(fill="x")
        tk.Button(nav, text="← Back", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat", padx=10, pady=4,
                  command=self._back).pack(side="left")
        self.fv_label = tk.Label(nav, text="", font=("Segoe UI Variable", 9, "italic"),
                                  bg=BG, fg=TEXT_GRAY)
        self.fv_label.pack(side="left", padx=16)
        self._generate_btn = tk.Button(
            nav, text="Generate PDF  →",
            font=("Segoe UI Variable", 10, "bold"),
            bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
            relief="flat", padx=16, pady=4,
            command=self._generate)
        self._generate_btn.pack(side="right")
        tk.Button(nav, text="Audit  →",
                  font=("Segoe UI Variable", 10),
                  bg=INFO_BG, fg=INFO_FG, activebackground=INFO_HOVER,
                  relief="flat", padx=12, pady=4,
                  command=self._show_audit).pack(side="right", padx=(0, 8))
        # 📌 Flag missing — manual companion to the auto-capture that
        # runs after generate(). Lets the user pin items the auto-detect
        # doesn't catch (e.g. "Moisture map", "Equipment log") so the
        # gap shows up in Hygiene the same way auto-detected ones do.
        tk.Button(nav, text="📌 Flag missing",
                  font=("Segoe UI Variable", 10),
                  bg=WARN_BG, fg=WARN_FG, activebackground=WARN_HOVER,
                  relief="flat", padx=12, pady=4,
                  command=self._open_flag_missing_dialog
                  ).pack(side="right", padx=(0, 8))
        # Scope edit — always available on the preview step so the user
        # can correct the parsed scope before generating the PDF. The
        # dialog re-parses on Save and writes a Scope.pdf into the job's
        # EMS/DOCS folder when one resolves.
        tk.Button(nav, text="📋 Edit Scope",
                  font=("Segoe UI Variable", 10),
                  bg=WARN_FG, fg=WHITE, activebackground=WARN_HOVER,
                  relief="flat", padx=12, pady=4,
                  command=self._open_scope_from_preview
                  ).pack(side="right", padx=(0, 8))
        # CLOSE OUT lives on the audit step now — moved 2026-05-06.
        # The Spreadsheet viewer moved to its own launcher tab on
        # 2026-05-07 — reachable via the "📒 Spreadsheet" toolstrip
        # entry. The inline button was removed so the snapshot nav
        # stays focused on the active workflow.
        # ➕ New Job — opens the New EMS Job dialog. The launcher's
        # top toolstrip hides New EMS Job by default; surfacing it
        # here keeps it one click away from the snapshot workflow,
        # which is when most new jobs get created (case incoming →
        # snapshot template needed → folder structure scaffolded).
        tk.Button(nav, text="➕ New Job",
                  font=("Segoe UI Variable", 10),
                  bg="#5C2C9D", fg=ON_ACCENT, activebackground="#421E70",
                  relief="flat", padx=12, pady=4,
                  command=self._open_new_job_tool
                  ).pack(side="right", padx=(0, 8))

        # Scrollable content area
        scroll = ScrollableFrame(self.frame_preview, bg=BG, padx=10)
        scroll.pack(fill="both", expand=True)
        self._pv_canvas    = scroll.canvas
        self._pv_scroll    = scroll
        # scroll.inner stretches to canvas width — that pins content to
        # the left edge on wide windows. Wrap the preview in a centered
        # column so the tables/cards sit in the middle without stretching.
        self.preview_inner = tk.Frame(scroll.inner, bg=BG)
        self.preview_inner.pack(side="top", anchor="n")

    # ── Parse & switch to preview ─────────────────────────────────────────────
    # ── Trello auto-pull ──────────────────────────────────────────────
    def _open_snapshot_picker(self):
        """Show a picker of cards currently in the ESTIMATING / SNAPSHOT
        lane on Trello. On select, pre-fills the input form (insured,
        carrier, DOL, cause) and the comments box from the card's desc
        + activity stream so the user doesn't have to copy/paste from
        the Trello tab."""
        try:
            import trello_client
        except Exception as ex:
            messagebox.showerror("Trello unavailable",
                                 f"Couldn't load trello_client:\n{ex}",
                                 parent=self)
            return
        cfg = config.load()
        list_id = (cfg.get("trello_snapshot_list_id") or "").strip()
        if not list_id:
            messagebox.showerror(
                "Snapshot lane not configured",
                "config.json is missing 'trello_snapshot_list_id'. "
                "Set it to the id of the ESTIMATING → SNAPSHOT lane "
                "(or whichever lane queues snapshots).",
                parent=self)
            return
        try:
            cards = trello_client.cards_in_list(list_id)
        except Exception as ex:
            messagebox.showerror("Trello fetch failed",
                                 f"Couldn't load SNAPSHOT lane:\n{ex}",
                                 parent=self)
            return
        if not cards:
            messagebox.showinfo(
                "Lane empty",
                "No cards are currently in the SNAPSHOT lane.",
                parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Pick a snapshot card")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        tk.Label(dlg,
                 text=f"{len(cards)} card{'s' if len(cards) != 1 else ''} "
                      f"in SNAPSHOT lane — pick one to pre-fill the form:",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 padx=14, pady=10).pack(anchor="w")
        list_box = tk.Frame(dlg, bg=WHITE,
                            highlightthickness=1, highlightbackground=BORDER)
        list_box.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        scroll = ScrollableFrame(list_box, bg=WHITE, height=380)
        scroll.pack(fill="both", expand=True)
        for card in cards:
            row = tk.Frame(scroll.inner, bg=WHITE,
                            padx=10, pady=6, cursor="hand2")
            row.pack(fill="x")
            tk.Label(row, text=card.get("name", "?"),
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=TEXT_DARK,
                     anchor="w", cursor="hand2").pack(fill="x")
            tk.Label(row, text=card.get("shortUrl", ""),
                     font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY,
                     anchor="w", cursor="hand2").pack(fill="x")
            tk.Frame(scroll.inner, bg=BORDER, height=1).pack(fill="x")
            def _pick(_e=None, _c=card):
                dlg.destroy()
                self._fill_from_trello_card(_c.get("id"))
            for w in (row, *row.winfo_children()):
                w.bind("<Button-1>", _pick)
        bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        bot.pack(fill="x")
        tk.Button(bot, text="Cancel", font=("Segoe UI Variable", 9),
                  bg=WHITE, fg=TEXT_DARK, activebackground=NEUTRAL_HOVER,
                  relief="solid", bd=1, padx=14, pady=4, cursor="hand2",
                  command=dlg.destroy).pack(side="right")
        dlg.update_idletasks()
        try:
            px, py = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self.winfo_width(), self.winfo_height()
            w = max(dlg.winfo_reqwidth(), 560)
            h = max(dlg.winfo_reqheight(), 480)
            dlg.geometry(f"{w}x{h}+{px + (pw-w)//2}+{py + (ph-h)//3}")
        except Exception:
            pass

    def _open_any_card_picker(self):
        """Search every in-scope Trello board by name and let the user
        pick a card to pre-fill the snapshot form. Same fill path as the
        lane picker — only the discovery differs."""
        try:
            import trello_client
        except Exception as ex:
            messagebox.showerror("Trello unavailable",
                                 f"Couldn't load trello_client:\n{ex}",
                                 parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Find any Trello card")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        # Header
        tk.Label(dlg, text="Search every board by name:",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=BG, fg=TEXT_DARK,
                 padx=14, pady=10).pack(anchor="w")

        # Search input — Enter or 250ms debounce kicks the search.
        srow = tk.Frame(dlg, bg=BG, padx=14)
        srow.pack(fill="x")
        query_var = tk.StringVar()
        entry = tk.Entry(srow, textvariable=query_var,
                          font=("Segoe UI Variable", 11),
                          bg=WHITE, fg=TEXT_DARK,
                          insertbackground=TEXT_DARK,
                          relief="solid", bd=1)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.focus_set()

        results_box = tk.Frame(dlg, bg=WHITE,
                                highlightthickness=1,
                                highlightbackground=BORDER)
        results_box.pack(fill="both", expand=True, padx=14, pady=(8, 10))
        scroll = ScrollableFrame(results_box, bg=WHITE, height=360)
        scroll.pack(fill="both", expand=True)
        status_lbl = tk.Label(dlg, text="Type a name and press Enter — "
                                          "or wait a moment.",
                                font=("Segoe UI Variable", 8, "italic"),
                                bg=BG, fg=TEXT_GRAY,
                                padx=14, anchor="w")
        status_lbl.pack(fill="x")

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        bot.pack(fill="x")
        tk.Button(bot, text="Cancel", font=("Segoe UI Variable", 9),
                  bg=WHITE, fg=TEXT_DARK, activebackground=NEUTRAL_HOVER,
                  relief="solid", bd=1, padx=14, pady=4, cursor="hand2",
                  command=dlg.destroy).pack(side="right")

        # Debounce search so each keystroke doesn't fire a Trello API
        # call. 250ms is enough to coalesce a fast typist into one
        # network round-trip.
        debouncer = ctkh.Debouncer(dlg, 250)

        def _render_results(cards, err=None):
            for w in scroll.inner.winfo_children():
                try: w.destroy()
                except tk.TclError: pass
            if err:
                status_lbl.config(text=f"Search failed: {err}")
                return
            if not cards:
                status_lbl.config(text="No matches.")
                return
            status_lbl.config(
                text=f"{len(cards)} match{'es' if len(cards) != 1 else ''} — "
                     f"click one to pre-fill the form.")
            for card in cards:
                row = tk.Frame(scroll.inner, bg=WHITE,
                                padx=10, pady=6, cursor="hand2")
                row.pack(fill="x")
                name = card.get("name") or "?"
                board_name = card.get("board") or ""
                list_name = card.get("list_name") or ""
                meta = " · ".join(b for b in (board_name, list_name) if b)
                tk.Label(row, text=name,
                         font=("Segoe UI Variable", 10, "bold"),
                         bg=WHITE, fg=TEXT_DARK,
                         anchor="w", cursor="hand2").pack(fill="x")
                tk.Label(row, text=meta,
                         font=("Segoe UI Variable", 8),
                         bg=WHITE, fg=TEXT_GRAY,
                         anchor="w", cursor="hand2").pack(fill="x")
                tk.Frame(scroll.inner, bg=BORDER,
                          height=1).pack(fill="x")
                def _pick(_e=None, _c=card):
                    dlg.destroy()
                    self._fill_from_trello_card(_c.get("card_id"))
                for w in (row, *row.winfo_children()):
                    w.bind("<Button-1>", _pick)

        def _do_search():
            q = (query_var.get() or "").strip()
            if len(q) < 2:
                _render_results([])
                if q:
                    status_lbl.config(
                        text="Keep typing — at least 2 characters.")
                return
            status_lbl.config(text=f"Searching for '{q}'…")
            # Threaded so a slow network doesn't freeze the dialog.
            def _bg():
                try:
                    res = trello_client.find_cards_by_name(
                        q, max_results=30)
                    err = None
                except Exception as ex:
                    res, err = [], str(ex)
                def _done():
                    try:
                        if dlg.winfo_exists():
                            _render_results(res, err=err)
                    except tk.TclError:
                        pass
                try:
                    dlg.after(0, _done)
                except tk.TclError:
                    pass
            threading.Thread(target=_bg, daemon=True).start()

        query_var.trace_add(
            "write", lambda *_: debouncer.fire(_do_search))
        entry.bind("<Return>", lambda _e: _do_search())

        dlg.update_idletasks()
        try:
            px, py = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self.winfo_width(), self.winfo_height()
            w = max(dlg.winfo_reqwidth(), 560)
            h = max(dlg.winfo_reqheight(), 480)
            dlg.geometry(f"{w}x{h}+{px + (pw-w)//2}+{py + (ph-h)//3}")
        except Exception:
            pass

    def _fill_from_trello_card(self, card_id):
        """Fetch one Trello card and populate the snapshot input form
        from it. Insured / carrier / DOL / cause come from the parsed
        card desc; the comments box gets the card's full activity feed
        formatted as `Author · Date\\nbody` blocks (newest first) so
        parse_comments can scan the whole thing for dates + activity
        keywords without modification."""
        import trello_client
        try:
            card = trello_client.get_card(card_id)
        except Exception as ex:
            messagebox.showerror("Trello fetch failed",
                                 f"Couldn't fetch card:\n{ex}", parent=self)
            return
        if not card:
            messagebox.showerror("Card missing",
                                 "Trello returned no card for that id.",
                                 parent=self)
            return

        fields = trello_client.parse_card_desc(card.get("desc"))
        cust = fields.get("CUSTOMER INFORMATION", {})
        ins  = fields.get("INSURANCE INFORMATION", {})
        prop = fields.get("PROPERTY DETAILS", {})

        # Defaulting / lookup-key choice happens inside the rules helper
        # below (commercial path prefers business title; everything else
        # prefers customer name).
        customer_name = (cust.get("CUSTOMER NAME") or "").strip()
        card_title    = (card.get("name") or "").strip()
        carrier = (ins.get("INSURANCE COMPANY") or "").strip()
        claim   = (ins.get("CLAIM NUMBER") or "").strip()
        dol   = (prop.get("DATE OF LOSS") or "").strip()
        cause = (prop.get("CAUSE OF LOSS") or "").strip()

        # Build the comments-box content first so the field-rules helper
        # can scan it for selfpay / cause / category / class hints.
        # Use get_all_comments so the paged history is included — the
        # default get_card payload only carries the last 50 actions, which
        # truncates older comments on long-running jobs (Trello's web UI
        # shows a "load more comments" button for the same reason).
        try:
            comment_actions = trello_client.get_all_comments(card_id) or []
        except Exception:
            comment_actions = [a for a in (card.get("actions") or [])
                               if a.get("type") == "commentCard"]
        comment_actions.reverse()
        blocks = []
        notes = fields.get("NOTES", {})
        for k, v in notes.items():
            if v:
                blocks.append(f"{k.title()}: {v}")
        for a in comment_actions:
            who = ((a.get("memberCreator") or {}).get("fullName") or "?")
            when = trello_client._fmt_action_date(a.get("date", ""))
            body = (a.get("data", {}).get("text") or "").strip()
            if not body:
                continue
            blocks.append(f"{who} · {when}\n{body}")
        comments_text = "\n\n".join(blocks)

        # Pull the "Subs" checklist as a fallback for the Sub/Vendor Log
        # when comment parsing finds no sub visits. Always-named "Subs"
        # per project rules; case-insensitive match. Check state ignored.
        subs_fallback = []
        for cl in (card.get("checklists") or []):
            if (cl.get("name") or "").strip().lower() == "subs":
                for it in (cl.get("checkItems") or []):
                    txt = (it.get("name") or "").strip()
                    if txt:
                        subs_fallback.append(txt)
        self._trello_subs_fallback = subs_fallback

        # Scan title + comments + Subs items for selfpay / commercial /
        # cause clues. card_title is passed as job_title so titles like
        # "Smith - Self Pay" are detected even when desc is sparse.
        scan_text = "\n".join([comments_text, "\n".join(subs_fallback)])
        insured, carrier_line, cause, customer_for_header = (
            apply_snapshot_field_rules(
                job_title=card_title, customer_name=customer_name,
                carrier=carrier, claim=claim, cause=cause,
                scan_text=scan_text))
        self._customer_for_header = customer_for_header

        def _set_entry(entry, value):
            try:
                entry.delete(0, "end")
                if value:
                    entry.insert(0, value)
            except Exception:
                pass
        _set_entry(self.e_insured, insured)
        _set_entry(self.e_carrier, carrier_line)
        _set_entry(self.e_dol,     dol)
        _set_entry(self.e_cause,   cause)

        try:
            self.txt_comments.delete("1.0", "end")
            self.txt_comments.insert("1.0", comments_text)
        except Exception:
            pass
        # Persist the pin so subsequent opens of this client land on
        # the right card automatically (job notes, audit, escalations).
        try:
            existing = persistence.get_trello_card_ids(insured)
            if card_id not in existing:
                persistence.set_trello_card_ids(insured,
                                                 list(existing) + [card_id])
        except Exception:
            pass
        show_toast(self,
                   f"Pre-filled from Trello: {insured or card.get('name')}",
                   kind="info")

    def _multi_unit_gate(self, insured: str) -> bool:
        """Check whether `insured` resolves to a multi-unit umbrella.
        When it does (≥ 2 sibling units in ems_db), show a picker and
        let the user decide between rolling up the property or
        snapshotting one specific unit.

        Returns True to continue parsing, False when the user
        cancelled. Side-effect: may update `self.e_insured` to the
        picked unit's display_name.

        Graceful degradation: if ems_db isn't reachable or has no
        sibling rows for this property, returns True without
        prompting (legacy behavior preserved)."""
        try:
            import ems_db
        except Exception:
            return True

        # Two ways the typed insured could be multi-unit:
        #  1. They typed the umbrella name ("Avila Apartments") — find
        #     children directly.
        #  2. They typed a unit ("Avila Apartments 1416") — find its
        #     siblings via find_units_of(parent_canon).
        try:
            umbrella_units = ems_db.find_units_of(ems_db.canon_key(insured))
        except Exception:
            umbrella_units = []
        if umbrella_units and len(umbrella_units) >= 2:
            return self._open_multi_unit_picker(
                property_name=insured,
                units=umbrella_units,
                came_in_as="umbrella")

        # Path 2: typed a unit — look up its property to surface siblings.
        try:
            prop_name, _unit_num = ems_db.detect_property_and_unit(insured)
            if prop_name:
                parent_canon = ems_db.canon_key(prop_name)
                sibs = ems_db.find_units_of(parent_canon)
                if len(sibs) >= 2:
                    return self._open_multi_unit_picker(
                        property_name=prop_name,
                        units=sibs,
                        came_in_as=insured)
        except Exception:
            pass
        return True

    def _open_multi_unit_picker(self, *, property_name, units, came_in_as):
        """Modal picker for multi-unit snapshot routing.

        Returns True when the user picked an option, False on cancel.
        On 'pick a specific unit' the Insured field is rewritten to
        that unit's display_name so the rest of the parse + render
        pipeline runs unchanged. On 'roll up the property' nothing
        is rewritten — the umbrella name stays."""
        dlg = tk.Toplevel(self)
        dlg.title(f"Multi-unit: {property_name}")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("520x500")
        except tk.TclError:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head, text=f"🏢 {property_name} has {len(units)} units",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
        tk.Label(head,
                 text=("Snapshot a single unit, or roll up the property? "
                       "Picking a unit replaces the Insured field with "
                       "that unit's name so per-unit comments / dates "
                       "resolve correctly."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=480, justify="left", anchor="w"
                 ).pack(fill="x", pady=(4, 0))

        body_wrap = tk.Frame(dlg, bg=BG, padx=14)
        body_wrap.pack(fill="both", expand=True)
        from tool_panel import ScrollableFrame
        scroll = ScrollableFrame(body_wrap, bg=BG, canvas_bg=WHITE)
        scroll.pack(fill="both", expand=True)

        result = {"chosen": None}   # None = cancel; "" = rollup; else display_name

        def _pick_unit(unit_name):
            result["chosen"] = unit_name
            dlg.destroy()

        def _pick_rollup():
            result["chosen"] = ""    # empty sentinel — keep umbrella
            dlg.destroy()

        # Rollup row at the top of the list — explicit option, not a
        # button-only afterthought.
        rollup_row = tk.Frame(scroll.inner, bg=LINK_BG,
                               highlightthickness=1,
                               highlightbackground="#1F4E8A")
        rollup_row.pack(fill="x", padx=2, pady=(2, 8))
        tk.Label(rollup_row,
                 text=f"  🏢 Roll up — snapshot all of {property_name}",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=LINK_BG, fg=LINK_FG,
                 anchor="w", padx=10, pady=8, cursor="hand2"
                 ).pack(fill="x")
        rollup_row.bind("<Button-1>", lambda _e: _pick_rollup())
        for c in rollup_row.winfo_children():
            c.bind("<Button-1>", lambda _e: _pick_rollup())

        # Individual unit rows.
        for u in units:
            row_f = tk.Frame(scroll.inner, bg=WHITE,
                              highlightthickness=1,
                              highlightbackground="#DDDDDD")
            row_f.pack(fill="x", padx=2, pady=2)
            inner = tk.Frame(row_f, bg=WHITE, padx=10, pady=6)
            inner.pack(fill="x")
            label = u.get("display_name") or u.get("canon_key", "")
            unit_num = u.get("unit_number") or ""
            text = f"  Unit {unit_num}  ·  {label}" if unit_num else f"  {label}"
            lbl = tk.Label(inner, text=text,
                            font=("Segoe UI Variable", 10),
                            bg=WHITE, fg=TEXT_DARK,
                            anchor="w", cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)
            pick = lambda _e, name=label: _pick_unit(name)
            lbl.bind("<Button-1>", pick)
            row_f.bind("<Button-1>", pick)
            inner.bind("<Button-1>", pick)

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(fill="x", side="bottom")
        tk.Button(bot, text="Cancel",
                  font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_DARK,
                  activebackground=NEUTRAL_HOVER,
                  relief="solid", bd=1, padx=12, pady=4, cursor="hand2",
                  command=dlg.destroy
                  ).pack(side="right")

        self.wait_window(dlg)
        if result["chosen"] is None:
            return False    # cancelled
        if result["chosen"]:
            # Replace Insured with the picked unit's display_name.
            try:
                self.e_insured.delete(0, tk.END)
                self.e_insured.insert(0, result["chosen"])
            except Exception:
                pass
        return True

    def _parse_and_preview(self):
        insured = self.e_insured.get().strip()
        if not insured:
            messagebox.showerror("Missing", "Please enter Insured / Job name.")
            return

        # Multi-unit gate. When the typed insured matches a property
        # umbrella with ≥ 2 known units in ems_db, prompt the user
        # to choose: snapshot a specific unit, or roll up the property.
        # Returns True when the user picked / confirmed; False when
        # they cancelled (abort the parse).
        if not self._multi_unit_gate(insured):
            return
        # _multi_unit_gate may have updated the Insured field — re-read.
        insured = self.e_insured.get().strip()

        comments = self.txt_comments.get("1.0", tk.END).strip()
        self._raw_comments = comments
        sub_rows, log_rows = parse_comments(comments)
        self.first_visit  = detect_first_visit(comments)
        self._scope_rooms = parse_scope(comments)

        # Always merge the Trello "Subs" checklist into sub_rows as
        # ground-truth confirmation: comment parsing is permissive and
        # easily fooled by email forwards, but the checklist is the
        # explicit list of subs the user maintains on the card. Dedupe
        # by vendor name (first " - " segment) so a checklist item
        # already represented by a parsed comment row is skipped.
        checklist_subs = getattr(self, "_trello_subs_fallback", None) or []
        if checklist_subs:
            def _vendor_of(text):
                # "Charles Taylor- Asbestos Testing - Bill SP" → "charles taylor"
                # Be permissive about the separator (" - " or "-").
                head = re.split(r"\s*-\s*|-", str(text or ""), maxsplit=1)[0]
                return head.strip().lower()
            already = {_vendor_of(s) for _d, _w, _a, s in sub_rows}
            for txt in checklist_subs:
                v = _vendor_of(txt)
                if v and v not in already:
                    # Use the checklist item's full text as the activity
                    # column so users see "Charles Taylor- Asbestos
                    # Testing - Bill SP" verbatim. Date/techs blank;
                    # sub column gets just the vendor for downstream
                    # display + future dedupe runs.
                    sub_rows.append(("", "", txt, _vendor_of(txt).title()))
                    already.add(v)

        carrier_in = self.e_carrier.get().strip()
        cause_in   = self.e_cause.get().strip()
        # Re-apply field rules so manual edits / pastes also benefit
        # from cause auto-detect and selfpay/commercial fallback. Only
        # rewrites the Carrier line when it's blank — never overrides
        # what the user explicitly typed. customer_for_header is left
        # alone when the carrier field is non-blank: a Trello pre-fill
        # already populated it, and a manual entry has no separate
        # customer source to populate it from.
        if not carrier_in:
            insured, carrier_in, cause_in, ch = apply_snapshot_field_rules(
                job_title=insured, customer_name="",
                carrier="", claim="", cause=cause_in, scan_text=comments)
            self._customer_for_header = ch
        elif not cause_in:
            _, _, cause_in, _ = apply_snapshot_field_rules(
                job_title=insured, customer_name="",
                carrier="x", claim="x",  # dummy non-empty so carrier path skipped
                cause="", scan_text=comments)

        self.insured = insured
        self.carrier = carrier_in
        self.dol     = self.e_dol.get().strip()
        self.cause   = cause_in

        self._populate_preview(sub_rows, log_rows)

        self.frame_input.pack_forget()
        self.frame_preview.pack(fill="both", expand=True)
        self._set_step_title(f"Preview  —  {insured}")
        self.fv_label.config(
            text=f"First visit: {self.first_visit}" if self.first_visit
            else "First visit: not detected")

        # Open the linked Trello card alongside the preview so the user
        # can cross-reference card details, comments, and checklists
        # without hunting for the tab. Only opens the first pinned card
        # — multi-card jobs would otherwise spam tabs on every preview.
        # Silent failure: a missing webbrowser, blocked browser, or
        # un-pinned client shouldn't prevent the preview from rendering.
        try:
            card_ids = persistence.get_trello_card_ids(insured) or []
            if card_ids:
                import webbrowser
                webbrowser.open(f"https://trello.com/c/{card_ids[0]}")
        except Exception:
            pass

    def _populate_preview(self, sub_rows, log_rows):
        for w in self.preview_inner.winfo_children():
            w.destroy()
        self.sub_entries = []
        self.log_entries = []

        # max_rows here only gates how many rows the UI will accept via
        # the "+ Add Row" button; rows beyond the PDF template's slot
        # count (8 subs, 53 logs) overflow onto a continuation page in
        # _generate. 500 is effectively unlimited for any real job and
        # protects against runaway add-row clicks.
        self._build_table("Sub / Vendor Log", sub_rows, self.sub_entries,
                          max_rows=500)

        tk.Frame(self.preview_inner, bg=BORDER, height=2).pack(fill="x", pady=6, padx=10)

        self._build_table("Daily Job Log", log_rows, self.log_entries,
                          max_rows=500)

        # Trello Comments summary card
        if log_rows or sub_rows:
            tk.Frame(self.preview_inner, bg=BORDER, height=2).pack(fill="x", pady=6, padx=10)
            card = tk.Frame(self.preview_inner, bg=WHITE,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", padx=10, pady=(0, 10))
            inner = tk.Frame(card, bg=WHITE, padx=12, pady=8)
            inner.pack(fill="x")
            tk.Label(inner, text="Trello Summary", font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_DARK).pack(anchor="w")

            # Date range
            dates = [r[0].strip() for r in log_rows if r[0].strip()]
            if dates:
                date_line = f"{dates[0]}  –  {dates[-1]}" if dates[0] != dates[-1] else dates[0]
                tk.Label(inner, text=f"Dates:       {date_line}",
                         font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")

            # Activity types (unique, in order)
            seen, acts = set(), []
            for r in log_rows:
                a = r[2].strip()
                if a and a not in seen:
                    seen.add(a); acts.append(a)
            if acts:
                tk.Label(inner, text=f"Activities:  {', '.join(acts)}",
                         font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY,
                         wraplength=480, justify="left").pack(anchor="w")

            # Techs (unique, across all log rows)
            seen_t, techs = set(), []
            for r in log_rows:
                for t in [x.strip() for x in r[3].split(",") if x.strip()]:
                    if t not in seen_t:
                        seen_t.add(t); techs.append(t)
            if techs:
                tk.Label(inner, text=f"Techs:       {', '.join(techs)}",
                         font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")

            # Subs/vendors
            seen_s, subs = set(), []
            for r in sub_rows:
                a = r[2].strip()
                if a and a not in seen_s:
                    seen_s.add(a); subs.append(a)
            if subs:
                tk.Label(inner, text=f"Subs:        {', '.join(subs)}",
                         font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")

        # Initial Inspection Notes card — surfaces parsed field-template
        # values (Date/Time/COL/Category/Areas/Storage/etc) for every
        # initial inspection in the raw comments. The Trello Summary
        # only flags "Initial Inspection" as an activity; this section
        # actually reads what the tech filed.
        try:
            from initial_notes_parser import (
                parse_initial_inspection_notes, _FIELDS as _INIT_FIELDS)
            parsed_initials = parse_initial_inspection_notes(
                getattr(self, "_raw_comments", "") or "")
        except Exception:
            parsed_initials = []
            _INIT_FIELDS = []
        if parsed_initials:
            tk.Frame(self.preview_inner, bg=BORDER, height=2).pack(
                fill="x", pady=6, padx=10)
            init_card = tk.Frame(self.preview_inner, bg=WHITE,
                                  highlightbackground=BORDER,
                                  highlightthickness=1)
            init_card.pack(fill="x", padx=10, pady=(0, 10))
            init_inner = tk.Frame(init_card, bg=WHITE, padx=12, pady=8)
            init_inner.pack(fill="x")
            n = len(parsed_initials)
            title = ("Initial Inspection Notes"
                     if n == 1 else f"Initial Inspection Notes ({n})")
            tk.Label(init_inner, text=title,
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_DARK).pack(anchor="w")
            # Each label rendered bold + each value rendered normal in
            # the same line — tk.Label can only carry one font, so we
            # use a tk.Text widget with tagged inserts. Width is in
            # characters; Text wraps long values automatically.
            label_order = [lbl for lbl, _aliases in _INIT_FIELDS]
            # Compute total visible lines so we can size the Text
            # exactly — no scrollbar, no empty space below.
            total_lines = 0
            for i, block in enumerate(parsed_initials):
                if n > 1:
                    total_lines += 1   # "Inspection N (date):" header
                total_lines += sum(1 for lbl in label_order if block.get(lbl))
            txt = tk.Text(
                init_inner, wrap="word", relief="flat",
                bg=WHITE, fg=TEXT_GRAY,
                font=("Segoe UI Variable", 8),
                height=max(1, total_lines),
                width=64, padx=0, pady=2,
                borderwidth=0, highlightthickness=0,
                cursor="arrow")
            txt.pack(anchor="w", fill="x", pady=(2, 0))
            # Three tag styles:
            #   header — bold, slightly darker, used when multi-block
            #   label  — bold dark-ish text for "Field Name:"
            #   value  — regular gray for the captured value
            txt.tag_configure(
                "header",
                font=("Segoe UI Variable", 8, "bold"),
                foreground=TEXT_DARK,
                spacing1=4)
            txt.tag_configure(
                "label",
                font=("Segoe UI Variable", 8, "bold"),
                foreground=TEXT_DARK)
            txt.tag_configure(
                "value",
                font=("Segoe UI Variable", 8),
                foreground=TEXT_GRAY)
            for i, block in enumerate(parsed_initials):
                if n > 1:
                    header = f"Inspection {i + 1}"
                    if block.get("Date"):
                        header += f" ({block['Date']})"
                    txt.insert("end", header + ":\n", "header")
                for lbl in label_order:
                    v = block.get(lbl)
                    if not v:
                        continue
                    txt.insert("end", "  • ", "value")
                    txt.insert("end", f"{lbl}:", "label")
                    txt.insert("end", f" {v}\n", "value")
            # Strip the trailing newline so there's no empty visual row.
            try:
                txt.delete("end-2c", "end-1c")
            except tk.TclError:
                pass
            txt.configure(state="disabled")

    def _build_table(self, title, rows, entry_list, max_rows):
        hdr = tk.Frame(self.preview_inner, bg=BG)
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(hdr, text=title, font=("Segoe UI Variable", 10, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        tk.Button(hdr, text="+ Add Row", font=("Segoe UI Variable", 8),
                  bg=GREEN, fg=WHITE, relief="flat", padx=6, pady=2,
                  command=lambda el=entry_list, mr=max_rows:
                      self._add_row(el, mr)).pack(side="right")

        col_hdr = tk.Frame(self.preview_inner, bg=BG)
        col_hdr.pack(fill="x", padx=12)
        for lbl, w in [("Date", 9), ("Weekday", 11), ("Activity", 34), ("Techs", 18)]:
            tk.Label(col_hdr, text=lbl, font=("Segoe UI Variable", 8, "bold"),
                     bg=BG, fg=TEXT_GRAY, width=w, anchor="w").pack(side="left", padx=2)

        self._table_frames = getattr(self, "_table_frames", {})
        container = tk.Frame(self.preview_inner, bg=BG)
        container.pack(fill="x", padx=10)
        self._table_frames[id(entry_list)] = container

        for row in rows:
            self._add_row(entry_list, max_rows, data=row, container=container)

    def _add_row(self, entry_list, max_rows, data=None, container=None):
        if len(entry_list) >= max_rows:
            return
        if container is None:
            container = self._table_frames.get(id(entry_list))
        if container is None:
            return

        d, wd, act, tech = data if data else ("", "", "", "")
        v = {
            "date":      tk.StringVar(value=d),
            "weekday":   tk.StringVar(value=wd),
            "activity":  tk.StringVar(value=act),
            "techs":     tk.StringVar(value=tech),
            "container": container,
        }
        entry_list.append(v)

        row_frame = tk.Frame(container, bg=BG)
        row_frame.pack(fill="x", pady=1)
        v["frame"] = row_frame

        handle = tk.Label(row_frame, text="⠿", font=("Segoe UI Variable", 10),
                          bg=BG, fg=TEXT_MUTED, cursor="size_ns")
        handle.pack(side="left", padx=(0, 2))
        handle.bind("<ButtonPress-1>",   lambda e, vv=v, el=entry_list: self._drag_start(e, vv, el))
        handle.bind("<B1-Motion>",        self._drag_motion)
        handle.bind("<ButtonRelease-1>",  self._drag_end)

        for key, w in [("date", 9), ("weekday", 11), ("activity", 34), ("techs", 18)]:
            ttk.Entry(row_frame, textvariable=v[key], width=w).pack(side="left", padx=2)

        # Auto-fill weekday when date is typed
        def _on_date(*_, vv=v):
            wd_val = get_weekday(vv["date"].get())
            if wd_val:
                vv["weekday"].set(wd_val)
        v["date"].trace_add("write", _on_date)

        tk.Button(row_frame, text="×", font=("Segoe UI Variable", 9, "bold"),
                  bg=BORDER, fg=FLAG_RED, relief="flat", width=2,
                  command=lambda vv=v, el=entry_list: self._delete_row(vv, el)
                  ).pack(side="left", padx=2)

    def _delete_row(self, v, entry_list):
        if v in entry_list:
            entry_list.remove(v)
        v["frame"].destroy()

    def _drag_start(self, event, v, entry_list):
        self._drag_data = {"v": v, "entry_list": entry_list}

    def _drag_motion(self, event):
        pass  # no visual ghost needed — drop on release is enough

    def _drag_end(self, event):
        if not self._drag_data:
            return
        v          = self._drag_data["v"]
        entry_list = self._drag_data["entry_list"]
        self._drag_data = None

        container  = v["container"]
        rows       = [vv for vv in entry_list if vv.get("container") is container]

        # Find the row the mouse landed on
        mouse_y    = event.y_root
        target_idx = len(rows) - 1
        for i, vv in enumerate(rows):
            frame_top = vv["frame"].winfo_rooty()
            frame_mid = frame_top + vv["frame"].winfo_height() // 2
            if mouse_y < frame_mid:
                target_idx = i
                break

        cur_idx = rows.index(v)
        if cur_idx == target_idx:
            return

        # Reorder entry_list
        entry_list.remove(v)
        entry_list.insert(target_idx, v)

        # Repack frames in new order
        for vv in entry_list:
            if vv.get("container") is container:
                vv["frame"].pack_forget()
        for vv in entry_list:
            if vv.get("container") is container:
                vv["frame"].pack(fill="x", pady=1)

    # ── Audit frame (Step 3) ─────────────────────────────────────────────────
    def _build_audit_frame(self):
        self.frame_audit = tk.Frame(self, bg=BG)
        self.frame_audit.pack(fill="both", expand=True)

        nav = tk.Frame(self.frame_audit, bg=BG, padx=20, pady=6)
        nav.pack(fill="x")
        tk.Button(nav, text="← New Snapshot", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat", padx=10, pady=4,
                  command=self._new_snapshot).pack(side="left")
        tk.Button(nav, text="← Edit Preview", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat", padx=10, pady=4,
                  command=self._back_to_preview).pack(side="left", padx=(6, 0))
        self.audit_summary = tk.Label(nav, text="", font=("Segoe UI Variable", 9, "italic"),
                                       bg=BG, fg=TEXT_GRAY)
        self.audit_summary.pack(side="left", padx=16)
        tk.Button(nav, text="Close", font=("Segoe UI Variable", 9),
                  bg=FLAG_RED, fg=WHITE, relief="flat", padx=10, pady=4,
                  command=self._close_tool).pack(side="right")
        tk.Button(nav, text="↺ Refresh", font=("Segoe UI Variable", 9),
                  bg=INFO_BG, fg=INFO_FG, activebackground=INFO_HOVER,
                  relief="flat", padx=10, pady=4,
                  command=self._show_audit).pack(side="right", padx=(0, 6))
        # CLOSE OUT — opens the Trello CLOSE OUT checklist for the
        # loaded client. Lives on the audit step (the user works the
        # checklist here once the audit confirms everything's in place).
        tk.Button(nav, text="📋 CLOSE OUT", font=("Segoe UI Variable", 9, "bold"),
                  bg=WARN_FG, fg=WHITE, activebackground=WARN_HOVER,
                  relief="flat", padx=12, pady=4,
                  command=self._open_close_out_dialog
                  ).pack(side="right", padx=(0, 6))
        # Spreadsheet viewer moved to its own launcher tab on
        # 2026-05-07 — see launcher's "📒 Spreadsheet" entry.

        # Scrollable results list
        scroll = ScrollableFrame(self.frame_audit, bg=BG, padx=10)
        scroll.pack(fill="both", expand=True)
        self._audit_canvas = scroll.canvas
        self._audit_inner  = scroll.inner
        self._audit_scroll = scroll

    def _open_new_job_tool(self):
        """Open the New EMS Job tool. Prefers in-launcher embedded
        switching when available (so the user stays in the same
        window); falls back to spawning a standalone process for
        snapshot-tool-as-standalone usage. Same lookup pattern other
        cross-tool buttons use."""
        host = getattr(self, "host", None)
        if host is not None:
            try:
                host.show_tool("new_job")
                return
            except Exception:
                pass
        try:
            paths.spawn_tool("new_job")
        except Exception as ex:
            messagebox.showerror("Couldn't open New EMS Job",
                                  str(ex), parent=self)

    def _open_close_out_dialog(self):
        """Open the CLOSE OUT Trello checklist for the loaded client.
        Resolves the client from the Insured form field; falls back to
        the Trello card name on the parsed payload if the field is
        empty (e.g. the user came in via auto-pull and hasn't typed)."""
        try:
            insured = self.e_insured.get().strip()
        except Exception:
            insured = ""
        if not insured:
            insured = (getattr(self, "insured", "") or "").strip()
        if not insured:
            messagebox.showinfo(
                "No client loaded",
                "Load a snapshot first — the CLOSE OUT dialog needs a "
                "client name to look up the Trello card.",
                parent=self)
            return
        try:
            from initial_upload_queue import open_close_out_dialog
        except Exception as ex:
            messagebox.showerror(
                "CLOSE OUT unavailable",
                f"Couldn't load the dialog module:\n{ex}",
                parent=self)
            return
        open_close_out_dialog(self, insured)

    def _show_audit(self):
        for w in self._audit_inner.winfo_children():
            w.destroy()

        self.audit_summary.config(text="Running audit…")
        self.frame_preview.pack_forget()
        self.frame_audit.pack(fill="both", expand=True)
        self._set_step_title("EMS Snapshot — Audit")
        # Cancel signal — the worker thread polls between jobs / SP
        # cross-checks and bails early when set. New audit run = fresh
        # event so a leftover Cancel from a prior run doesn't poison it.
        self._audit_cancel = threading.Event()
        self.update()

        log_rows = [(v["date"].get(), v["weekday"].get(),
                     v["activity"].get(), v["techs"].get())
                    for v in self.log_entries if v["date"].get().strip()] or None

        def _set_status(msg):
            # Hop back to the UI thread to update the status label.
            # If the snapshot window was closed while the audit thread
            # was still running, the label widget no longer exists —
            # just swallow the TclError instead of bubbling it up.
            def _apply(m=msg):
                try:
                    if self.audit_summary.winfo_exists():
                        self.audit_summary.config(text=m)
                except tk.TclError:
                    pass
            try:
                self.after(0, _apply)
            except tk.TclError:
                pass

        # "Audit Only" with no insured triggers a full year sweep —
        # hundreds of jobs. Show per-job progress so the user can tell
        # it's actually working (not hung). Single-job audits skip this
        # since one job finishes in <1s.
        is_full_sweep = not (self.insured or "").strip()
        cancel_evt = self._audit_cancel

        def _progress(idx, total, name):
            if total <= 1:
                return
            # Trim very long names so the status label doesn't wrap.
            short = (name[:32] + "…") if len(name) > 33 else name
            _set_status(f"Auditing {idx} of {total} — {short}")

        # Mount a Cancel button into the nav strip so the user has a
        # way out when SharePoint walks stall on a slow share. The
        # button removes itself when the audit finishes.
        cancel_btn_holder = [None]
        def _show_cancel_button():
            try:
                if not self.audit_summary.winfo_exists():
                    return
                btn = tk.Button(
                    self.audit_summary.master, text="Cancel",
                    font=("Segoe UI Variable", 9), bg=FLAG_RED, fg=WHITE,
                    activebackground="#922B21", relief="flat",
                    padx=10, pady=2,
                    command=lambda: (cancel_evt.set(),
                                      _set_status("Cancelling…")))
                btn.pack(side="left", padx=(8, 0))
                cancel_btn_holder[0] = btn
            except tk.TclError:
                pass

        def _hide_cancel_button():
            try:
                btn = cancel_btn_holder[0]
                if btn is not None and btn.winfo_exists():
                    btn.destroy()
            except tk.TclError:
                pass
            cancel_btn_holder[0] = None

        self.after(0, _show_cancel_button)

        def _run():
            try:
                _set_status("Running audit — checking forms and photos…")
                results, err = run_audit(
                    current_insured=self.insured or None,
                    current_log_rows=log_rows,
                    current_carrier=self.carrier or None,
                    progress_cb=_progress if is_full_sweep else None,
                    folder_override=getattr(self, "_audit_folder_override", None),
                )
            except Exception as ex:
                results, err = None, f"Audit error: {ex}"
            # Cross-check OneDrive PICS vs SharePoint so the snapshot's
            # mini audit shows the same 📷 photo count and 📥 SP +N new
            # badges as the main Run Audit panel. The SharePoint walk
            # touches a network share and can take 5-30s per job —
            # for full sweeps that's prohibitive across hundreds of
            # jobs, so only enrich flagged rows (the only place SP +N
            # actually matters anyway).
            if results and not cancel_evt.is_set():
                try:
                    from run_audit_gui import enrich_with_sharepoint
                    from sharepoint import build_sharepoint_folder_index
                    run_date = datetime.today().strftime("%m-%d-%Y")
                    sp_targets = [r for r in results if r.get("flagged")] \
                        if is_full_sweep else list(results)
                    sp_total = len(sp_targets)
                    if sp_total:
                        # Sweep mode: enumerate every SP subfolder once
                        # and reuse the list for every client. Single-job
                        # audits don't need this — re-walking the share
                        # for one client is fine.
                        folder_index = None
                        match_cache = {}
                        if is_full_sweep:
                            _set_status(
                                "Indexing SharePoint folders "
                                "(one-time scan)…")
                            folder_index = build_sharepoint_folder_index()
                        for j, r in enumerate(sp_targets, 1):
                            if cancel_evt.is_set():
                                break
                            if is_full_sweep:
                                _set_status(
                                    f"Cross-checking SharePoint photos "
                                    f"({j} of {sp_total} flagged)…")
                            else:
                                _set_status(
                                    "Cross-checking SharePoint photos "
                                    "(this can take a few seconds)…")
                            enrich_with_sharepoint(
                                r, run_date,
                                folder_index=folder_index,
                                match_cache=match_cache)
                except Exception:
                    pass
            self.after(0, _hide_cancel_button)
            if cancel_evt.is_set():
                self.after(0, lambda: self._render_audit(
                    results, err or "Audit cancelled — partial results below."))
            else:
                self.after(0, lambda: self._render_audit(results, err))

        threading.Thread(target=_run, daemon=True).start()

    def _render_audit(self, results, err):
        # Stash the latest results so _open_sp_download_dialog_for can
        # tell the hidden Run Audit helper which list to re-render when
        # the SP dialog mutates state (Mark in OD, etc.).
        self._snapshot_audit_results = results
        # Background sync to the SharePoint Snapshots workbook — this
        # is the cross-team source of truth so other admins can pull
        # the .xlsx directly. Only fires on a clean audit run; errors
        # are swallowed inside the module so a failed sync never
        # disrupts the snapshot UI. See snapshots_excel.sync_jobs.
        if results and not err:
            try:
                import snapshots_excel
                snapshots_excel.sync_jobs(results)
            except Exception:
                pass
        if err:
            self.audit_summary.config(text="Folder not found")
            wrap = tk.Frame(self._audit_inner, bg=BG)
            wrap.pack(pady=20, padx=20, fill="x")
            # If the PDF was just generated, lead with a success banner
            # so the user sees the snapshot completed before they hit
            # the audit error. "i just need the snapshot" — the file is
            # already on disk; the audit step is supplementary.
            pdf_path = getattr(self, "_last_snapshot_pdf", "") or ""
            if pdf_path and os.path.isfile(pdf_path):
                ok = tk.Frame(wrap, bg="#E8F5EE",
                              highlightthickness=1,
                              highlightbackground=GREEN_DARK)
                ok.pack(fill="x", pady=(0, 12))
                tk.Label(ok, text="✓  Snapshot PDF saved",
                         font=("Segoe UI Variable", 10, "bold"),
                         bg="#E8F5EE", fg=GREEN_DARK
                         ).pack(anchor="w", padx=12, pady=(8, 0))
                tk.Label(ok, text=pdf_path,
                         font=("Segoe UI Variable", 8),
                         bg="#E8F5EE", fg=TEXT_DARK,
                         wraplength=480, justify="left"
                         ).pack(anchor="w", padx=12, pady=(2, 0))
                btn_row = tk.Frame(ok, bg="#E8F5EE")
                btn_row.pack(fill="x", padx=12, pady=(6, 10))
                tk.Button(btn_row, text="📂 Open PDF",
                          font=("Segoe UI Variable", 9, "bold"),
                          bg=GREEN, fg=WHITE,
                          activebackground=GREEN_DARK, relief="flat",
                          padx=12, pady=4,
                          command=lambda p=pdf_path: os.startfile(p)
                          ).pack(side="left")
                tk.Button(btn_row, text="📁 Open Folder",
                          font=("Segoe UI Variable", 9), bg=SURFACE_2,
                          fg=TEXT_DARK, relief="flat", padx=10, pady=4,
                          command=lambda p=pdf_path: os.startfile(
                              os.path.dirname(p))
                          ).pack(side="left", padx=(8, 0))
            tk.Label(wrap,
                     text=("Audit step (optional)"
                           if pdf_path and os.path.isfile(pdf_path)
                           else "Audit failed"),
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=BG, fg=TEXT_DARK).pack(anchor="w", pady=(0, 4))
            tk.Label(wrap, text=f"⚠  {err}", font=("Segoe UI Variable", 9),
                     bg=BG, fg=FLAG_RED, wraplength=480, justify="left").pack(anchor="w")
            tk.Label(wrap, text="Enter the exact folder name to retry:",
                     font=("Segoe UI Variable", 9, "bold"), bg=BG).pack(anchor="w", pady=(10, 2))
            row = tk.Frame(wrap, bg=BG)
            row.pack(fill="x")
            folder_var = tk.StringVar()
            ttk.Entry(row, textvariable=folder_var, width=40).pack(side="left", padx=(0, 8))
            tk.Button(row, text="Search", font=("Segoe UI Variable", 9, "bold"),
                      bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                      relief="flat", padx=10, pady=3,
                      command=lambda: self._retry_audit(folder_var.get().strip())
                      ).pack(side="left")
            return

        _audit_export.write_audit_md(
            results,
            source=f"Snapshot — {self.insured}" if self.insured else "Snapshot",
            trello_notes=getattr(self, "_raw_comments", ""))
        # Persistence key for checkbox/resolved state — today's date, shared
        # with Run Audit if that ran today too
        _snapshot_run_date = datetime.today().strftime("%m-%d-%Y")
        flagged_count = sum(1 for r in results if r["flagged"])
        resolved = [0]

        def _update_status():
            # Window can close mid-audit; guard against a destroyed label.
            try:
                if not self.audit_summary.winfo_exists():
                    return
                rem = flagged_count - resolved[0]
                self.audit_summary.config(
                    text=f"{len(results)} jobs  ·  {rem} flagged  ·  {len(results) - flagged_count + resolved[0]} OK")
            except tk.TclError:
                pass

        _update_status()

        # Lazy helper: every per-row widget that delegates to the daily
        # Run Audit's dialogs (notes editor, escalation, right-click,
        # SP, Find Folder re-audit) goes through this. Created once per
        # render and re-used across every card.
        helper = self._get_audit_helper()

        # Repeat-offender lookup — pulled once before the loop so the
        # ↻ N× chip can be rendered without per-row I/O. Same source
        # the daily Run Audit reads from.
        try:
            audit_count_idx = _audit_export.get_audit_count_index()
        except Exception:
            audit_count_idx = {}

        # Done-stages helper from run_audit_gui (file-walk based).
        # Lazy import so a load failure doesn't block the snapshot from
        # rendering the rest of the row.
        try:
            from run_audit_gui import _detect_done_stages
        except Exception:
            _detect_done_stages = lambda _p: []
        # Stage-chip color map mirrors run_audit_gui's _STAGE_CHIP_COLORS.
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
        # Latest-stage source — parses the client's job notes file for
        # the most recent stage line. Lazy import for the same reason.
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
            _jn_has_note     = lambda *_a, **_k: False
            _jn_has_any_note = lambda *_a, **_k: False
            _jn_load_note    = lambda *_a, **_k: ""
            _jn_find_any_note = lambda *_a, **_k: (None, "")
            _jn_parse_stages = lambda _t: []
            _jn_notes_path   = lambda *_a, **_k: ""
        try:
            from job_widgets import extract_job_year as _extract_job_year
        except Exception:
            _extract_job_year = lambda _p: datetime.today().year

        current_card = None
        for r in results:
            border_color = "#1A6FBF" if r["is_current"] else BORDER
            border_width = 2 if r["is_current"] else 1
            card = tk.Frame(self._audit_inner, bg=WHITE,
                            highlightbackground=border_color,
                            highlightthickness=border_width)
            card.pack(fill="x", padx=6, pady=2)
            # Right-click context menu (Change folder / Clear saved
            # path / Clear Commercial / Reset all memory). Same menu
            # the daily Run Audit shows. Wired to snapshot's own
            # _retry_audit so a folder change re-runs the snapshot
            # audit (not the daily Run Audit).
            try:
                attach_card_context_menu(
                    self, [card], r["client"],
                    run_date=_snapshot_run_date,
                    audit_base=AUDIT_BASE,
                    on_change_folder=lambda p:
                        self._retry_audit(os.path.basename(p)))
            except Exception:
                pass
            row = tk.Frame(card, bg=WHITE, padx=10, pady=6)
            row.pack(fill="x")

            badge_bg  = FLAG_RED if r["flagged"] else GREEN
            badge_txt = "FLAG" if r["flagged"] else " OK "
            badge_lbl = tk.Label(row, text=badge_txt, font=("Segoe UI Variable", 8, "bold"),
                                 bg=badge_bg, fg=WHITE, padx=4)
            badge_lbl.pack(side="left")

            # ↻ N× repeat-offender chip — visible when this folder has
            # been flagged in many past audits without resolving. Color
            # ramps from gold (5+) to orange (10+) to deep red (20+) so
            # chronic backlog drag is impossible to miss. Same source +
            # thresholds as the daily Run Audit.
            rep_count = audit_count_idx.get(
                ((r.get("folder") or "").strip(),
                 (r.get("unit") or "").strip().lower()), 0)
            if r.get("flagged") and rep_count >= 5:
                rep_bg = "#7B1818" if rep_count >= 20 else (
                          "#E67E22" if rep_count >= 10 else "#C39A37")
                tk.Label(row, text=f"↻ {rep_count}x",
                         font=("Segoe UI Variable", 7, "bold"),
                         bg=rep_bg, fg=WHITE, padx=3
                         ).pack(side="left", padx=(2, 0))

            # Saved-memory chips (📁 folder override / C commercial / 🗒 note)
            # right next to the badge, same position as in Run Audit.
            try:
                render_memory_pin(row, r["client"],
                                   path=r.get("path"), bg=WHITE)
            except Exception:
                pass

            detail = tk.Frame(row, bg=WHITE)
            detail.pack(side="left", fill="x", expand=True)

            name_row = tk.Frame(detail, bg=WHITE)
            name_row.pack(fill="x")

            label_text = f"  {r['client']}"
            if r.get("is_current"):
                label_text += "  ◀ current"
            # Match Run Audit's folder-name disambiguation: when the matched
            # folder differs from the run-doc client (reversed name, prior
            # year tag), surface the actual folder name in parens so the
            # user knows which job got picked.
            if r.get("found") and r.get("folder") and \
                    r["folder"].lower() != r["client"].lower():
                label_text += f"  ({r['folder']})"
            tk.Label(name_row, text=label_text, font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=LINK_FG if r.get("is_current") else TEXT_DARK,
                     anchor="w").pack(side="left", fill="x", expand=True)

            # New-loss pill — visible status tag matching the daily Run Audit.
            if r.get("new_loss"):
                tk.Label(name_row, text=" NEW LOSS ",
                         font=("Segoe UI Variable", 7, "bold"),
                         bg=WARN_BG, fg=WARN_FG,
                         padx=4, pady=1
                         ).pack(side="left", padx=(6, 0))

            # ─── RIGHT-SIDE WIDGETS — pack order mirrors run_audit_gui's
            # _render_one_card so the visual layout reads identically:
            #   [done_stages][latest_stage][📷][📥SP][🚩][📌][🗒][📁]
            # Each side="right" pack pushes prior right-side widgets
            # further left. 🗒 uses the `before=📌` trick to insert
            # right next to 📁 (matching Run Audit's exact placement).

            # 1. 📁 OD — rightmost. Matches Run Audit's row pill exactly
            # (link_button with the "📁 OD" label) so the snapshot row
            # and the daily audit row read as the same affordance.
            open_dir_btn = None
            if r.get("path"):
                open_dir_btn = link_button(
                    name_row, "📁 OD", padx=6, pady=1,
                    command=lambda p=r["path"]: os.startfile(p),
                    tooltip="Open OD folder in Explorer "
                            "(right-click row to change folder)")
                open_dir_btn.pack(side="right")

            # 2. 📌 Trello pin button — always present so the user can
            # pin/unpin from any audit row. Green-fill when pinned,
            # white outline otherwise. Same dialog Job Notes uses.
            try:
                pinned_count = len(
                    persistence.get_trello_card_ids(r["client"]) or [])
            except Exception:
                pinned_count = 0
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
            def _pin_done(_ids, _btn=pin_btn, _client=r["client"]):
                new_count = len(persistence.get_trello_card_ids(_client) or [])
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
            pin_btn.configure(
                command=lambda _client=r["client"], _cb=_pin_done:
                    open_trello_pin_dialog(self, _client, on_pinned=_cb))
            pin_btn.pack(side="right", padx=(0, 4))

            # 3. 🚩 escalation — only when aged ≥3 biz days AND folder
            # was found (Run Audit's exact condition). Color flips to
            # ✅🚩 once persistence.is_escalated(today, client) is True.
            if helper is not None and int(r.get("aging") or 0) >= 3 \
                    and r.get("found"):
                run_date_for_check = _snapshot_run_date
                try:
                    already = persistence.is_escalated(
                        run_date_for_check, r["client"])
                except Exception:
                    already = False
                esc_btn = tk.Button(
                    name_row,
                    text="✅ 🚩" if already else "🚩",
                    font=("Segoe UI Emoji", 10),
                    bg=WHITE, fg=SUCCESS_FG if already else FLAG_RED,
                    relief="flat", padx=2, cursor="hand2")
                def _esc_cb(rr=r, b=esc_btn,
                            run_date=run_date_for_check):
                    try:
                        escalated = persistence.is_escalated(
                            run_date, rr["client"])
                    except Exception:
                        escalated = False
                    try:
                        b.configure(
                            text="✅ 🚩" if escalated else "🚩",
                            fg=SUCCESS_FG if escalated else FLAG_RED)
                    except tk.TclError:
                        pass
                esc_btn.configure(
                    command=lambda rr=r, cb=_esc_cb:
                        helper._open_escalation_dialog(rr, on_marked=cb))
                esc_btn.pack(side="right", padx=(0, 2))

            # 📌 Flag missing — same per-row button the Daily Run audit
            # and the IUQ have. Stage tag is "audit" so Hygiene
            # attributes the gap to the audit step (matches Run Audit's
            # version). Per-row affordance is consistent across all
            # three tools — every change made to the audit row in
            # run_audit_gui must mirror here.
            try:
                _card_id_for_flag = (persistence.get_trello_card_id(
                    r.get("client") or "") or "")
            except Exception:
                _card_id_for_flag = ""
            tk.Button(name_row,
                      text="📌 Flag missing",
                      font=("Segoe UI Variable", 8, "bold"),
                      bg=LINK_BG, fg=LINK_FG,
                      activebackground=LINK_HOVER,
                      relief="flat", padx=6, pady=1, cursor="hand2",
                      command=lambda c=r.get("client") or "",
                                       cid=_card_id_for_flag:
                          self._open_flag_missing_for_row(c, cid)
                      ).pack(side="right", padx=(0, 4))

            # 4. 📥 SP three-state — always shown so the dialog can be
            # re-opened from any row (incl. for "+ Pin folder" manual
            # attachment when no matches exist yet).
            sp_new = r.get("sharepoint_new", 0)
            sp_matches = r.get("sharepoint_matches") or []
            sp_match_count = len(sp_matches)
            if sp_new > 0:
                sp_text = f"📥 SP +{sp_new} new"
                sp_bg, sp_fg, sp_active = "#FFF4D6", "#A6772A", "#FFE9B0"
            elif sp_match_count > 0:
                sp_text = f"📁 SP ({sp_match_count})"
                sp_bg, sp_fg, sp_active = "#EAF3FB", "#2C6FA8", "#D6E7F4"
            else:
                sp_text = "📁 SP"
                sp_bg, sp_fg, sp_active = "#F4F4F4", "#888888", "#E8E8E8"
            tk.Button(name_row,
                      text=sp_text,
                      font=("Segoe UI Variable", 8, "bold"),
                      bg=sp_bg, fg=sp_fg, activebackground=sp_active,
                      relief="flat", padx=6, pady=1, cursor="hand2",
                      command=lambda rr=r:
                          self._open_sp_download_dialog_for(rr)
                      ).pack(side="right", padx=(0, 4))

            # 5. 📷 photos — always shown when PICS path exists. Green
            # when >0, red when 0.
            pics_n = r.get("pics_count", 0)
            pics_p = r.get("pics_path") or ""
            if pics_p:
                pic_bg, pic_fg = (("#E8F5EE", GREEN_DARK) if pics_n > 0
                                   else ("#FBEAE5", "#A04025"))
                tk.Button(name_row,
                          text=f"📷 {pics_n}",
                          font=("Segoe UI Variable", 8, "bold"),
                          bg=pic_bg, fg=pic_fg,
                          activebackground=pic_bg,
                          relief="flat", padx=6, pady=1, cursor="hand2",
                          command=lambda p=pics_p: os.startfile(p)
                          ).pack(side="right", padx=(0, 4))

            # 6. 🗒 Notes — uses `before=` to insert right next to 📁,
            # mirroring Run Audit's exact placement. Falls back to a
            # plain side="right" pack if 📁 isn't present (no path).
            if helper is not None:
                _year_for_check = _extract_job_year(r.get("path"))
                try:
                    has_note_any = (persistence.has_note(r["client"])
                                     or _jn_has_any_note(r["client"]))
                except Exception:
                    has_note_any = False
                note_fg = TEXT_DARK if has_note_any else "#B8B8B8"
                notes_btn = tk.Button(
                    name_row, text="🗒",
                    font=("Segoe UI Emoji", 11),
                    bg=WHITE, fg=note_fg,
                    relief="flat", padx=2, cursor="hand2",
                    command=lambda c=r["client"], p=r.get("path"):
                        helper._open_notes_dialog(c, p))
                # Hover popover — timeline + expected files. Mirrors the
                # audit panel so the same affordance reads the same way
                # in both tools.
                def _build_notes_hover(parent,
                                        _yr=_year_for_check,
                                        _cn=r["client"]):
                    import job_notes_gui as _jn
                    _jn.build_hover_popover(parent, _yr, _cn)
                attach_rich_tooltip(notes_btn, _build_notes_hover)
                # Find the widget that comes AFTER 📁 in the pack chain
                # so we can insert 🗒 immediately to 📁's left.
                if open_dir_btn is not None:
                    after_dir = None
                    saw_dir = False
                    for s in name_row.pack_slaves():
                        if s is open_dir_btn:
                            saw_dir = True
                            continue
                        try:
                            if saw_dir and s.pack_info().get("side") == "right":
                                after_dir = s
                                break
                        except Exception:
                            pass
                    if after_dir is not None:
                        notes_btn.pack(side="right", padx=(0, 2),
                                        before=after_dir)
                    else:
                        notes_btn.pack(side="right", padx=(0, 2))
                else:
                    notes_btn.pack(side="right", padx=(0, 2))

                # Latest-stage label (right of 🗒). Reads job notes for
                # the most recent stage line + age.
                latest_stage = ""
                stage_age_days = None
                if has_note_any:
                    try:
                        note_text = _jn_load_note(_year_for_check, r["client"])
                        stages = _jn_parse_stages(note_text or "")
                        if stages:
                            latest_stage = stages[-1]
                            np = _jn_notes_path(_year_for_check, r["client"])
                            if np and os.path.isfile(np):
                                mt = datetime.fromtimestamp(
                                    os.path.getmtime(np))
                                stage_age_days = _biz_days_since(mt)
                    except Exception:
                        pass
                if latest_stage:
                    age_str = (f" · {stage_age_days}d"
                               if stage_age_days is not None else "")
                    tk.Label(name_row, text=f"{latest_stage}{age_str}",
                             font=("Segoe UI Variable", 7),
                             bg=WHITE, fg=TEXT_GRAY
                             ).pack(side="right", padx=(0, 2))

            # 7. Done-stages chips — what kind of work this folder
            # actually has photos for (Demo / Contents / Equipment etc).
            # Distinct from latest_stage which comes from the job-note
            # text. Packed reversed so visual order matches the walk.
            done_stages = []
            if r.get("path"):
                try:
                    done_stages = _detect_done_stages(r["path"]) or []
                except Exception:
                    done_stages = []
            for label in reversed(done_stages):
                bg, fg = _STAGE_CHIP_COLORS.get(label,
                                                 ("#EEEEEE", TEXT_DARK))
                tk.Label(name_row, text=label,
                         font=("Segoe UI Variable", 7, "bold"),
                         bg=bg, fg=fg, padx=4, pady=0
                         ).pack(side="right", padx=(0, 2))

            # 8. Find Folder + Rename — only when audit couldn't resolve
            # a folder for the client. Both pack last (leftmost on the
            # right side) so they're prominent.
            if not r.get("found") and helper is not None:
                from tkinter import filedialog as _fd
                def _find_folder(rr=r, c=card):
                    path = _fd.askdirectory(
                        title=f"Select folder for: {rr['client']}",
                        initialdir=(AUDIT_BASE if os.path.isdir(AUDIT_BASE)
                                     else os.path.expanduser("~")))
                    if not path:
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
                    persistence.set_folder_path(rr["client"], path)
                    self._retry_audit(os.path.basename(path))
                tk.Button(name_row, text="Find Folder",
                          font=("Segoe UI Variable", 8),
                          bg=WARN_BG, fg=WARN_FG,
                          activebackground=WARN_HOVER,
                          relief="flat", padx=8, pady=2, cursor="hand2",
                          command=_find_folder
                          ).pack(side="right", padx=(0, 4))
                # Rename — delegates to RunAuditApp's helper so the
                # actual rename logic stays in one place.
                if hasattr(helper, "_rename_folder"):
                    tk.Button(name_row, text="Rename",
                              font=("Segoe UI Variable", 8),
                              bg=LINK_BG, fg=LINK_FG,
                              activebackground=LINK_HOVER,
                              relief="flat", padx=8, pady=2,
                              cursor="hand2",
                              command=lambda rr=r, c=card:
                                  helper._rename_folder(rr, c)
                              ).pack(side="right", padx=(0, 2))

            if not r["flagged"]:
                if r.get("is_current"):
                    current_card = card
                    _add_trello_toggle(card, getattr(self, "_raw_comments", ""))
                continue

            items = []
            for m in (r.get("missing") or []):
                items.append((f"Empty folder: {m}", FLAG_RED, False, False, False))
            for fi in (r.get("form_issues") or []):
                is_scope_item = (fi.strip().lower() == "scope" and r.get("is_current"))
                items.append((fi, FLAG_RED, False, _is_commercial_form(fi), is_scope_item))
            for pi in (r.get("photo_issues") or []):
                items.append((pi, FLAG_RED, "docusketch" in pi.lower(), False, False))
            # Dispute / rejection callouts pulled from the run-doc text.
            # Same red-row treatment as the daily Run Audit panel.
            for ni in (r.get("note_issues") or []):
                items.append((ni, FLAG_RED, False, False, False))
            if r["aging"] >= 3:
                last_str = r["last"].strftime("%m/%d/%y") if r["last"] else "never"
                items.append((f"{r['aging']}d inactive (last: {last_str})", "#E67E22", False, False, False))

            if not items:
                if r.get("is_current"):
                    current_card = card
                continue

            card_resolved      = [False]
            all_vars           = []

            has_commercial = any(ic for _, _, _, ic, _ in items)
            commercial = CommercialToggle(name_row, r["client"],
                                          bg=WHITE, activebackground=WHITE,
                                          selectcolor=WHITE)
            if has_commercial:
                commercial.checkbutton.pack(side="right", padx=(0, 4))

            def _make_toggle(var, lbl, item_color, all_v, bl, ca, cr,
                             client=None, issue=None):
                def _toggle():
                    if client and issue:
                        persistence.set_resolved(_snapshot_run_date, client,
                                                  persist_key(issue), var.get())
                    if var.get():
                        lbl.config(fg=TEXT_MUTED, font=("Segoe UI Variable", 8, "overstrike"))
                    else:
                        lbl.config(fg=item_color, font=("Segoe UI Variable", 8))
                    now_done = all(v.get() for v in all_v)
                    was_done = cr[0]
                    if now_done and not was_done:
                        cr[0] = True
                        bl.config(text=" OK ", bg=GREEN)
                        ca.config(highlightbackground="#A8D5B5")
                        resolved[0] += 1
                        _update_status()
                    elif not now_done and was_done:
                        cr[0] = False
                        bl.config(text="FLAG", bg=FLAG_RED)
                        ca.config(highlightbackground=BORDER)
                        resolved[0] -= 1
                        _update_status()
                return _toggle

            def _make_import_action(cp, var, lbl, all_v, bl, ca, cr,
                                       client_name=""):
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
                    # When the docusketch isn't ready yet — log the request
                    # on the Trello card AND set a daily reminder via the
                    # Hygiene panel until the zip actually arrives. Closes
                    # the dialog after recording.
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
                        picker = tk.Toplevel(self)
                        picker.title("Select Docusketch Zip")
                        picker.resizable(False, False)
                        picker.grab_set()
                        pf = tk.Frame(picker, bg=BG, padx=16, pady=14)
                        pf.pack()
                        tk.Label(pf, text="Multiple zips found — pick one:",
                                 font=("Segoe UI Variable", 10, "bold"), bg=BG).pack(anchor="w", pady=(0,8))
                        pick_var = tk.StringVar(value=zips[0])
                        for z in zips[:6]:
                            tk.Radiobutton(pf, text=z, variable=pick_var, value=z,
                                           font=("Segoe UI Variable", 8), bg=BG,
                                           activebackground=BG).pack(anchor="w", pady=2)
                        result = [None]
                        def _pick(): result[0] = pick_var.get(); picker.destroy()
                        tk.Button(pf, text="Import", font=("Segoe UI Variable", 10, "bold"),
                                  bg=GREEN, fg=WHITE, relief="flat", padx=12, pady=4,
                                  command=_pick).pack(pady=(12, 0), fill="x")
                        picker.wait_window()
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
                    # Recycle the source zip — every Downloads import
                    # auto-cleans the source per user direction. Uses
                    # send2trash so a misclick is recoverable.
                    try:
                        from wc_zip_import import trash_imported_zips
                        trash_imported_zips(zip_path)
                    except Exception:
                        pass
                    var.set(True)
                    lbl.config(fg=TEXT_MUTED, font=("Segoe UI Variable", 8, "overstrike"))
                    if all(v.get() for v in all_v) and not cr[0]:
                        cr[0] = True
                        bl.config(text=" OK ", bg=GREEN)
                        ca.config(highlightbackground="#A8D5B5")
                        resolved[0] += 1
                        _update_status()
                    # Auto-clear any pending docusketch-request reminder
                    # for this client — the zip just arrived. Best-effort
                    # lookup; if no card is matched there's nothing to clear.
                    try:
                        import docusketch_requests as dr
                        if client_name:
                            hit = dr.find_card_for_client(client_name)
                            if hit is not None:
                                dr.resolve(hit["card_id"])
                    except Exception:
                        pass
                    # Tick the Trello PHYSICAL SKETCH checklist item.
                    _ds_ticked = []
                    try:
                        import persistence as _per
                        import trello_autotick as _at
                        _cid = (_per.get_trello_card_id(client_name)
                                or "") if client_name else ""
                        if _cid:
                            _ds_ticked = _at.autotick(
                                _cid, events=("docusketch_imported",),
                                client=client_name)
                    except Exception:
                        _ds_ticked = []
                    _ds_msg = f"Extracted to:\n{ds_folder}"
                    if _ds_ticked:
                        _ds_msg += ("\n\n✓ Ticked Trello: "
                                    + ", ".join(it for _cl, it in _ds_ticked))
                    messagebox.showinfo("Docusketch Imported", _ds_msg)
                return _do

            def _make_wc_action_snapshot(cp, var, lbl, all_v, bl, ca, cr,
                                          *, is_photo, item_txt,
                                          client_name=""):
                """Workcenter import for the Snapshot audit. Mirrors
                run_audit_gui's `_make_workcenter_action` but stripped
                down (no card-walk refresh, no carry-forward bookkeeping
                — Snapshot's audit list is single-shot for this client).

                Photos go into the highest-priority PICS variant under
                the job, with a stage subfolder appended when the audit
                row is stage-tagged ('Demo pics', 'Mold pics', etc.).
                Forms go into EMS/DOCS where check_forms looks. Multi-
                part zip sets (`attachments-part-N-of-M.zip`) extract
                all parts together via the shared grouper."""
                from run_audit_gui import (
                    WORKCENTER_URL, WC_ATTACHMENTS_RE, WC_DOCUMENTS_RE,
                    _stage_folder_for_item, _resolve_all_pics_folders,
                )
                import wc_zip_import as _wcz
                zip_re = WC_ATTACHMENTS_RE if is_photo else WC_DOCUMENTS_RE
                label  = "attachments" if is_photo else "documents"
                kind   = "photos" if is_photo else "forms"
                def _do():
                    # ToolPanel is a tk.Frame — `tk.Toplevel(self)` works
                    # but Tk picks the master via path traversal which
                    # has flaked into "bad window path name" errors when
                    # the audit re-renders mid-flight. Anchor explicitly
                    # to the actual Toplevel ancestor so the new dialog
                    # always has a stable, alive parent.
                    parent = self._toplevel() or self
                    _pr = _wcz.prompt_for_wc_zip(parent,
                                                  workcenter_url=WORKCENTER_URL,
                                                  label=label, kind=kind)
                    if not _pr:
                        return
                    if isinstance(_pr, list):
                        chosen_label, chosen_paths = ("picked files", _pr)
                    else:
                        groups = _wcz.find_wc_zips(DOWNLOADS, zip_re)
                        if not groups:
                            messagebox.showerror("Not Found",
                                f"No Workcenter {kind} zip found in "
                                f"Downloads.\n\nExpected: {label}*.zip\n\n"
                                "Tip: use “📁 Pick a file…” to choose any "
                                "file manually.")
                            return
                        picked = _wcz.pick_zip_group(parent, groups, label=label)
                        if picked is None:
                            return
                        chosen_label, chosen_paths = picked
                    if is_photo:
                        # Multi-unit: ask which unit before extracting.
                        chosen_unit_path = None
                        try:
                            from multi_unit_gui import list_unit_subfolders
                            unit_list = list_unit_subfolders(cp)
                        except Exception:
                            unit_list = []
                        if unit_list:
                            try:
                                from run_audit_gui import _ask_unit_for_import
                                chosen_unit_path = _ask_unit_for_import(
                                    self, unit_list, kind="photos",
                                    client_name=client_name)
                                if chosen_unit_path is None:
                                    return
                            except Exception:
                                chosen_unit_path = None
                        if chosen_unit_path:
                            target = os.path.join(
                                chosen_unit_path, "EMS", "PICS")
                            os.makedirs(target, exist_ok=True)
                        else:
                            pics_opts = _resolve_all_pics_folders(cp)
                            if not pics_opts:
                                target = os.path.join(cp, "EMS", "PICS")
                                os.makedirs(target, exist_ok=True)
                            else:
                                target = pics_opts[0][1]
                        stage = _stage_folder_for_item(item_txt)
                        if stage:
                            target = os.path.join(target, stage)
                            os.makedirs(target, exist_ok=True)
                        # Sticky-home override (see _make_workcenter_action
                        # for full reasoning) — when ≥2 image basenames in
                        # the WC zip already exist somewhere under PICS,
                        # route the batch to that subfolder instead of the
                        # stage-derived one.
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
                        docs = (find_docs_dir(base)
                                or os.path.join(base, "DOCS"))
                        os.makedirs(docs, exist_ok=True)
                        target = docs
                    try:
                        _wcz.place_import_paths(chosen_paths, target)
                    except Exception as ex:
                        messagebox.showerror("Extract Error", str(ex))
                        return
                    # Photos only: HEIC → JPEG, then sort into per-room
                    # subfolders (Bed 1, Bath 2, Garage…) when filenames
                    # carry room labels. Both no-op safely otherwise.
                    if is_photo:
                        try:
                            from wc_zip_import import (convert_heic_in_dir,
                                                        organize_by_room)
                            convert_heic_in_dir(target)
                            organize_by_room(target)
                        except Exception:
                            pass
                    # Recycle every part of the WC zip — multi-part
                    # archives all get trashed since they were all
                    # extracted together.
                    try:
                        from wc_zip_import import trash_imported_zips
                        trash_imported_zips(chosen_paths)
                    except Exception:
                        pass
                    # Persistence is the source of truth — write it
                    # FIRST so that even if the audit body got re-
                    # rendered mid-import, the resolution survives the
                    # next audit pass. Widget updates below are best-
                    # effort against the possibly-stale row.
                    try:
                        persistence.set_resolved(
                            _snapshot_run_date, client_name,
                            persist_key(item_txt), True)
                    except Exception:
                        pass
                    try:
                        var.set(True)
                        lbl.config(fg=TEXT_MUTED,
                                    font=("Segoe UI Variable", 8, "overstrike"))
                        if all(v.get() for v in all_v) and not cr[0]:
                            cr[0] = True
                            bl.config(text=" OK ", bg=GREEN)
                            ca.config(highlightbackground="#A8D5B5")
                            resolved[0] += 1
                            _update_status()
                    except tk.TclError:
                        # Audit list got re-rendered out from under us
                        # — widgets we captured are gone. Persistence
                        # was already written; the next render will
                        # pick up the resolved state.
                        pass
                    msg = f"Extracted {kind} to:\n{target}"
                    if len(chosen_paths) > 1:
                        msg = (f"Extracted {len(chosen_paths)} parts "
                               f"({chosen_label}) to:\n{target}")
                    messagebox.showinfo("Workcenter Imported", msg)
                return _do

            def _make_ds_action_snapshot(cp, var, lbl, all_v, bl, ca, cr,
                                          *, item_txt, client_name=""):
                """DocuSign Final-Paperwork import for the Snapshot audit.
                Mirrors run_audit_gui's `_make_docusign_action` — same
                find/extract module, same target (EMS/DOCS) — minus the
                shared item_records sibling re-walk that lives only in
                run_audit_gui. Snapshot's audit is single-shot for this
                client so a re-render picks up sibling rows naturally.

                Opens a branch dialog up-front: the user can either
                ✍ Request the DocuSign via Trello (posts a comment +
                records a Hygiene pending entry) or proceed to import
                a signed packet they already have in Downloads. The
                "I sent out a DocuSign" path is the Request branch —
                missing this before the snapshot smart-import refactor.
                """
                from run_audit_gui import DOWNLOADS, find_docs_dir
                def _do():
                    parent = self._toplevel() or self
                    # ── Branch dialog (Request via Trello / Import) ──
                    dlg = tk.Toplevel(parent)
                    dlg.title("DocuSign")
                    dlg.resizable(False, False)
                    try:
                        dlg.transient(parent)
                    except Exception:
                        pass
                    dlg.grab_set()
                    wf = tk.Frame(dlg, bg=BG, padx=20, pady=16)
                    wf.pack()
                    tk.Label(wf,
                              text=(f"DocuSign Final Paperwork for "
                                    f"{client_name or 'this client'}"),
                              font=("Segoe UI Variable", 10, "bold"),
                              bg=BG).pack(anchor="w")
                    tk.Label(wf,
                              text=("Send the paperwork via Trello "
                                    "(Hygiene will nag daily until it's "
                                    "signed), or import a signed packet "
                                    "from Downloads."),
                              font=("Segoe UI Variable", 9),
                              bg=BG, fg=TEXT_GRAY,
                              wraplength=420, justify="left"
                              ).pack(anchor="w", pady=(4, 12))

                    def _request_via_trello():
                        try:
                            from docusketch_requests import (
                                find_card_for_client)
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
                                f"'{client_name}'. Open the card "
                                f"manually and request DocuSign via "
                                f"Trello.",
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
                                   f"DocuSign paperwork sent to "
                                   f"{email} — awaiting signature. "
                                   f"The Hygiene panel's '✍ Docusign "
                                   f"pending' section will nag daily "
                                   f"until it's signed.")
                        else:
                            msg = (f"Posted to {entry['card_name']}.\n\n"
                                   f"No email on file — pinged "
                                   f"{dsr.KIMBERLY_HANDLE} on the "
                                   f"Trello card to get one. Hygiene "
                                   f"will show the row with a "
                                   f"'✉ Got email' button.")
                        if not entry.get("comment_posted", True):
                            msg = ("Recorded locally, but the Trello "
                                   "comment failed to post. Open the "
                                   "card and post manually.")
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
                              fg=TEXT_DARK, relief="flat", padx=12,
                              pady=4, command=dlg.destroy
                              ).pack(side="left")
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
                            "Downloads.\n\nExpected: "
                            "<Client>_Final_Paperwork.zip")
                        return
                    chosen = zips[0]
                    if len(zips) > 1:
                        parent = self._toplevel() or self
                        pick_dlg = tk.Toplevel(parent)
                        pick_dlg.title("Select DocuSign zip")
                        pick_dlg.resizable(False, False)
                        pick_dlg.transient(parent)
                        pick_dlg.grab_set()
                        pf = tk.Frame(pick_dlg, bg=BG, padx=16, pady=14)
                        pf.pack()
                        tk.Label(pf,
                                 text="Multiple DocuSign zips found — pick one:",
                                 font=("Segoe UI Variable", 10, "bold"), bg=BG
                                 ).pack(anchor="w", pady=(0, 8))
                        pick_var = tk.IntVar(value=0)
                        for idx, fn in enumerate(zips[:6]):
                            tk.Radiobutton(pf, text=fn, variable=pick_var,
                                            value=idx,
                                            font=("Segoe UI Variable", 8),
                                            bg=BG, activebackground=BG
                                            ).pack(anchor="w", pady=2)
                        picked = [None]
                        def _pick():
                            picked[0] = pick_var.get()
                            pick_dlg.destroy()
                        tk.Button(pf, text="Import",
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
                    # Recycle the source DocuSign packet.
                    try:
                        from wc_zip_import import trash_imported_zips
                        trash_imported_zips(zip_path)
                    except Exception:
                        pass
                    try:
                        persistence.set_resolved(_snapshot_run_date,
                                                  client_name,
                                                  persist_key(item_txt), True)
                    except Exception:
                        pass
                    try:
                        var.set(True)
                        lbl.config(fg=TEXT_MUTED,
                                    font=("Segoe UI Variable", 8, "overstrike"))
                        if all(v.get() for v in all_v) and not cr[0]:
                            cr[0] = True
                            bl.config(text=" OK ", bg=GREEN)
                            ca.config(highlightbackground="#A8D5B5")
                            resolved[0] += 1
                            _update_status()
                    except tk.TclError:
                        pass
                    summary = dsi.summarize_landed(landed)
                    messagebox.showinfo(
                        "DocuSign Imported",
                        f"Extracted to:\n{docs}\n\nForms: {summary}")
                return _do

            def _make_smart_import_action_snapshot(
                    cp, var, lbl, all_v, bl, ca, cr,
                    *, item_txt, client_name,
                    is_photo, is_ds_signable, show_wc):
                """Snapshot mirror of run_audit_gui._make_smart_import_action.
                Per the 3-way audit parity rule — same unified scan-and-
                dispatch behavior as the Daily Run audit's 📥 Import.
                """
                def _do():
                    # Lazy-import what we need at fire-time so module
                    # load order isn't sensitive to whether run_audit_gui
                    # has finished initializing its module-level regexes.
                    try:
                        from run_audit_gui import (
                            WC_ATTACHMENTS_RE as _ATT_RE,
                            WC_DOCUMENTS_RE   as _DOCS_RE)
                    except Exception:
                        _ATT_RE = _DOCS_RE = None
                    candidates = []
                    if show_wc:
                        try:
                            from wc_zip_import import find_wc_zips as _f
                        except Exception:
                            _f = None
                        if _f is not None and is_photo and _ATT_RE:
                            try:
                                groups = _f(DOWNLOADS, _ATT_RE)
                            except Exception:
                                groups = []
                            if groups:
                                candidates.append((
                                    f"📷 Workcenter photos "
                                    f"({len(groups)} in Downloads)",
                                    _make_wc_action_snapshot(
                                        cp, var, lbl, all_v, bl, ca, cr,
                                        is_photo=True,
                                        item_txt=item_txt,
                                        client_name=client_name)))
                        if _f is not None and not is_photo and _DOCS_RE:
                            try:
                                groups = _f(DOWNLOADS, _DOCS_RE)
                            except Exception:
                                groups = []
                            if groups:
                                candidates.append((
                                    f"📄 Workcenter docs "
                                    f"({len(groups)} in Downloads)",
                                    _make_wc_action_snapshot(
                                        cp, var, lbl, all_v, bl, ca, cr,
                                        is_photo=False,
                                        item_txt=item_txt,
                                        client_name=client_name)))
                    if is_ds_signable:
                        try:
                            import docusign_import as _dsi
                            ds_zips = _dsi.find_docusign_zips(
                                DOWNLOADS, client_hint=client_name)
                        except Exception:
                            ds_zips = []
                        # Always surface DS — even with no zip in
                        # Downloads, the underlying action opens the
                        # branch dialog with "✍ Send DocuSign via
                        # Trello" so the user can request signatures
                        # from inside the snapshot audit (parity with
                        # daily-run audit per the 3-way rule).
                        if ds_zips:
                            ds_label = (f"📝 DocuSign signed packet "
                                        f"({len(ds_zips)} in Downloads)")
                        else:
                            ds_label = "✍ Send DocuSign via Trello"
                        candidates.append((
                            ds_label,
                            _make_ds_action_snapshot(
                                cp, var, lbl, all_v, bl, ca, cr,
                                item_txt=item_txt,
                                client_name=client_name)))
                    if not candidates:
                        looked_for = []
                        if show_wc and is_photo:
                            looked_for.append(
                                "Workcenter attachments*.zip")
                        elif show_wc:
                            looked_for.append(
                                "Workcenter documents*.zip")
                        if is_ds_signable:
                            looked_for.append(
                                "<Client>_Final_Paperwork.zip "
                                "(DocuSign packet)")
                        looked_msg = ("\n  • ".join(looked_for)
                                       if looked_for
                                       else "(nothing applicable)")
                        messagebox.showinfo(
                            "Nothing to import",
                            f"No importable zip found in Downloads.\n"
                            f"\nLooked for:\n  • {looked_msg}",
                            parent=self)
                        return
                    if len(candidates) == 1:
                        candidates[0][1]()
                        return
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
                               font=("Segoe UI Variable", 9),
                               bg=SURFACE_2, fg=TEXT_DARK,
                               relief="flat", padx=12, pady=4,
                               command=dlg.destroy
                               ).pack(pady=(12, 0))
                return _do

            for item_txt, item_color, is_ds, is_comm, is_scope in items:
                already = bool(persistence.is_resolved(_snapshot_run_date,
                                                         r["client"],
                                                         persist_key(item_txt)))
                var = tk.BooleanVar(value=already)
                all_vars.append(var)
                item_row = tk.Frame(detail, bg=WHITE)
                item_row.pack(fill="x", pady=1)
                lbl_fg   = "#AAAAAA" if already else item_color
                lbl_font = ("Segoe UI Variable", 8, "overstrike") if already else ("Segoe UI Variable", 8)
                lbl = tk.Label(item_row, text=item_txt,
                               font=lbl_font, bg=WHITE,
                               fg=lbl_fg, anchor="w")
                lbl.pack(side="left", padx=(2, 0))
                toggle_fn = _make_toggle(var, lbl, item_color, all_vars,
                                         badge_lbl, card, card_resolved,
                                         client=r["client"], issue=item_txt)
                if is_comm:
                    commercial.register(var, toggle_fn,
                                        persist_key(item_txt))
                if is_ds and r["path"]:
                    tk.Button(item_row, text="📥 Import",
                              font=("Segoe UI Variable", 7), bg=INFO_BG, fg=INFO_FG,
                              activebackground=INFO_HOVER, relief="flat",
                              padx=4, pady=1, cursor="hand2",
                              command=_make_import_action(r["path"], var, lbl,
                                                          all_vars, badge_lbl,
                                                          card, card_resolved,
                                                          client_name=r.get("client", ""))
                              ).pack(side="left", padx=(4, 0))
                if is_scope and r["path"]:
                    tk.Button(item_row, text="📋 Add Scope",
                              font=("Segoe UI Variable", 7), bg=INFO_BG, fg=INFO_FG,
                              activebackground=INFO_HOVER, relief="flat",
                              padx=4, pady=1, cursor="hand2",
                              command=lambda p=r["path"]: self._open_scope_dialog(p)
                              ).pack(side="left", padx=(4, 0))
                # 📥 Import — unified scanner mirrors the Daily Run
                # audit's smart-import per the 3-way audit parity rule
                # (feedback-audit-snapshot-parity). Scans Downloads,
                # routes to WC docs / WC photos / DocuSign packet
                # automatically. Multi-zip picker when more than one
                # kind is in Downloads.
                show_wc = bool(_CFG.get("workcenter_url") and r.get("path"))
                is_photo_item = item_txt in (r.get("photo_issues") or [])
                is_form_item  = item_txt in (r.get("form_issues") or [])
                is_ds_signable = is_form_item and any(
                    kw in (item_txt or "").lower()
                    for kw in ("auth", "atp",
                               "customer info", "cif",
                               "customer equip", "cer",
                               "cert of satisf", "cos"))
                can_show_import = (
                    (show_wc and not is_ds and (is_photo_item or is_form_item))
                    or (is_ds_signable and r.get("path")))
                if can_show_import:
                    tk.Button(
                        item_row, text="📥 Import",
                        font=("Segoe UI Variable", 7),
                        bg="#7B5BA8", fg=ON_ACCENT,
                        activebackground="#5C4081",
                        relief="flat", padx=4, pady=1, cursor="hand2",
                        command=_make_smart_import_action_snapshot(
                            r["path"], var, lbl, all_vars, badge_lbl,
                            card, card_resolved,
                            item_txt=item_txt,
                            client_name=r.get("client", ""),
                            is_photo=is_photo_item,
                            is_ds_signable=bool(
                                is_ds_signable and r.get("path")),
                            show_wc=bool(
                                show_wc and not is_ds
                                and (is_photo_item or is_form_item)))
                    ).pack(side="left", padx=(4, 0))
                tk.Checkbutton(item_row, variable=var, bg=WHITE,
                               activebackground=WHITE, selectcolor=WHITE,
                               command=toggle_fn
                               ).pack(side="right")

            # Sticky-Commercial auto-apply: cascade once if loaded True
            # from persistence (master Checkbutton command does NOT fire
            # on init).
            commercial.auto_apply_if_sticky()

            # If every item for this card was already resolved from a prior
            # session, flip the badge to OK immediately on render
            if (all_vars and all(v.get() for v in all_vars)
                    and not card_resolved[0]):
                card_resolved[0] = True
                badge_lbl.config(text=" OK ", bg=GREEN)
                card.config(highlightbackground="#A8D5B5")
                resolved[0] += 1
                _update_status()

            if r.get("is_current"):
                current_card = card
                _add_trello_toggle(card, getattr(self, "_raw_comments", ""))

        if current_card:
            self.update_idletasks()
            y = current_card.winfo_y()
            total = self._audit_inner.winfo_height()
            if total > 0:
                self._audit_canvas.yview_moveto(max(0, (y - 40) / total))

    def _get_audit_helper(self):
        """Lazy-init the hidden RunAuditApp helper. Used as a delegate for
        every "use the real Run Audit logic" path in the snapshot's audit
        step — SP download dialog, notes editor, escalation flag dialog,
        right-click context menu, etc.

        Returns the helper instance or None if the import/init fails.
        Caller should handle None by skipping the action (or showing a
        small error). The helper is re-used across calls so we only pay
        the init cost once per snapshot session.
        """
        try:
            from run_audit_gui import RunAuditApp
        except Exception:
            return None

        helper = getattr(self, "_run_audit_helper", None)
        if helper is not None:
            try:
                if helper.winfo_exists():
                    helper.run_date = datetime.today().strftime("%m-%d-%Y")
                    return helper
            except tk.TclError:
                pass

        # A silent subclass that skips the automatic last-doc parse.
        # The snapshot already has its own job in hand.
        class _SilentRunAuditHelper(RunAuditApp):
            def _restore_last_doc(self_inner):
                pass
        host = tk.Frame(self)
        try:
            helper = _SilentRunAuditHelper(host)
        except Exception:
            return None
        helper.host = self
        helper.run_date = datetime.today().strftime("%m-%d-%Y")
        self._run_audit_helper = helper
        return helper

    def _open_sp_download_dialog_for(self, r):
        """Open the same SharePoint download dialog the daily Run Audit
        uses, scoped to one job."""
        helper = self._get_audit_helper()
        if helper is None:
            messagebox.showerror(
                "SharePoint dialog unavailable",
                "Couldn't initialize Run Audit helper.",
                parent=self)
            return
        # Helper's _last_results / _render are used by the dialog when
        # the user takes an action (Mark in OD, Wrong job, etc.) so the
        # parent audit row updates. Snapshot has its own render — point
        # the helper's hooks at our re-render so changes propagate here.
        snapshot_results = getattr(self, "_snapshot_audit_results", None)

        def _snapshot_render(_results, _err):
            try:
                if snapshot_results is not None:
                    self._render_audit(snapshot_results, None)
            except Exception:
                pass
        helper._last_results = snapshot_results or [r]
        helper._render = _snapshot_render

        try:
            helper._open_sharepoint_download_dialog(r)
        except Exception as ex:
            messagebox.showerror(
                "SharePoint dialog failed",
                f"{ex}", parent=self)

    def _retry_audit(self, folder_name):
        if not folder_name:
            return
        for w in self._audit_inner.winfo_children():
            w.destroy()
        self.audit_summary.config(text="Running audit…")
        self.update()

        log_rows = [(v["date"].get(), v["weekday"].get(),
                     v["activity"].get(), v["techs"].get())
                    for v in self.log_entries if v["date"].get().strip()] or None

        def _run():
            try:
                results, err = run_audit(
                    current_insured=folder_name,
                    current_log_rows=log_rows,
                    current_carrier=self.carrier or None,
                )
            except Exception as ex:
                results, err = None, f"Audit error: {ex}"
            self.after(0, lambda: self._render_audit(results, err))

        threading.Thread(target=_run, daemon=True).start()

    def _prompt_audit_folder_override(self, insured):
        """Thin shim — uses the shared dialog but returns the folder
        path (or '' / None) instead of (name, folder) since the insured
        is already typed into the input form."""
        from job_widgets import prompt_audit_folder_override
        return prompt_audit_folder_override(
            self, prompt_for_name=False,
            insured=insured,
            initial_dir=AUDIT_BASE,
            title="Audit folder",
            intro=("Pick the exact job folder if the matcher keeps "
                   "missing — otherwise leave it on auto-match."))

    def _new_snapshot(self):
        self._scope_rooms = []
        self.frame_audit.pack_forget()
        self.frame_input.pack(fill="both", expand=True)
        self._set_step_title("EMS Snapshot")

    def _back_to_preview(self):
        if not self.insured:
            return
        self.frame_audit.pack_forget()
        self.frame_preview.pack(fill="both", expand=True)
        self._set_step_title(f"Preview  —  {self.insured}")

    # ── Scope (from preview nav — resolves path at save time) ────────────────
    def _open_scope_from_preview(self):
        def _find_path():
            try:
                year = datetime.today().year
                year_folder = next(
                    (os.path.join(AUDIT_BASE, d) for d in os.listdir(AUDIT_BASE)
                     if os.path.isdir(os.path.join(AUDIT_BASE, d)) and str(year) in d
                     and not ("LA" in d.upper() and "FIRE" in d.upper())),
                    None)
                if not year_folder:
                    return None
                def _norm(s):
                    return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', s.lower())).strip()
                def _match(folder, name):
                    nl, fl = _norm(name), _norm(folder)
                    return (len(nl) >= 4 and nl in fl) or (len(fl) >= 4 and fl in nl)
                name = self.insured or ""
                for d in os.listdir(year_folder):
                    if _match(d, name):
                        return os.path.join(year_folder, d)
                if ',' in name:
                    last, first = [p.strip() for p in name.split(',', 1)]
                    rev = f"{first} {last}"
                    for d in os.listdir(year_folder):
                        if _match(d, rev):
                            return os.path.join(year_folder, d)
            except Exception:
                pass
            return None

        self._open_scope_dialog(_find_path())

    # ── Scope dialog ──────────────────────────────────────────────────────────
    @staticmethod
    def _serialize_scope_rooms(rooms):
        """Render parsed rooms back to the line-based form the strict
        block parser eats: room name on its own line, items on
        following lines, blank line between rooms."""
        out = []
        for i, rm in enumerate(rooms or []):
            if i > 0:
                out.append("")
            out.append(rm.get("room", "").strip() or "Room")
            for item in rm.get("items", []):
                out.append(item.strip())
        return "\n".join(out)

    @staticmethod
    def _parse_scope_blocks(raw):
        """Forgiving block parser for the edit dialog. Blank lines
        separate rooms; first non-blank line of each block is the
        room name, the rest are items. No material-keyword filter —
        the user has already confirmed this IS the scope, so we
        don't drop items just because they don't say 'drywall' or
        'remove'. Returns [] if the text has no items."""
        rooms = []
        current = None
        for line in (raw or "").splitlines():
            s = line.strip()
            if not s:
                if current and current["items"]:
                    rooms.append(current)
                current = None
                continue
            if current is None:
                current = {"room": s.rstrip('.').strip() or "Room",
                           "items": []}
            else:
                current["items"].append(s)
        if current and current["items"]:
            rooms.append(current)
        return rooms

    def _open_scope_dialog(self, job_path):
        dlg = tk.Toplevel(self)
        dlg.title("Scope Preview")
        dlg.geometry("560x520")
        dlg.configure(bg=BG)
        dlg.resizable(True, True)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg=GREEN, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Scope Preview", font=("Segoe UI Variable", 12, "bold"),
                 bg=GREEN, fg=WHITE).pack()
        tk.Label(hdr, text=self.insured, font=("Segoe UI Variable", 9),
                 bg=GREEN, fg="#B2DFC4").pack()

        # Single editable Text widget — pre-filled with the auto-parsed
        # scope when the scan grabbed one, empty otherwise. Either way
        # the user can correct, paste, delete, retype freely. We
        # re-parse at Save time so the edited text is the source of
        # truth, not the original scan.
        info = tk.Frame(dlg, bg=BG, padx=12)
        info.pack(fill="x", pady=(8, 0))
        if self._scope_rooms:
            msg = (f"Auto-detected {len(self._scope_rooms)} room(s) "
                   f"from Trello — edit below if anything is wrong, "
                   f"then Save.")
            msg_fg = TEXT_DARK
        else:
            msg = ("No scope auto-detected. Paste the scope notes below "
                   "(room names on their own lines, items underneath), "
                   "then Save.")
            msg_fg = FLAG_RED
        tk.Label(info, text=msg, font=("Segoe UI Variable", 9), bg=BG, fg=msg_fg,
                 justify="left", wraplength=520, anchor="w"
                 ).pack(fill="x")

        outer = tk.Frame(dlg, bg=BG, padx=12, pady=8)
        outer.pack(fill="both", expand=True)
        text_box = tk.Text(outer, font=("Consolas", 9),
                            bg=WHITE, relief="flat", borderwidth=1,
                            highlightthickness=1, highlightbackground=BORDER,
                            wrap="word", undo=True)
        sb = tk.Scrollbar(outer, orient="vertical", command=text_box.yview)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(sb)
        except Exception:
            pass
        text_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        text_box.pack(side="left", fill="both", expand=True)
        if self._scope_rooms:
            text_box.insert("1.0", self._serialize_scope_rooms(self._scope_rooms))

        bot = tk.Frame(dlg, bg=BG, padx=12, pady=10)
        bot.pack(fill="x")
        tk.Button(bot, text="Close", font=("Segoe UI Variable", 9),
                  bg=SURFACE_2, fg=TEXT_DARK, relief="flat", padx=12, pady=4,
                  command=dlg.destroy).pack(side="left")

        def _save():
            raw = text_box.get("1.0", tk.END).strip()
            if not raw:
                messagebox.showwarning("Empty",
                    "Type or paste some scope text first.", parent=dlg)
                return
            # Prefer the blank-line block parser — it's lossless
            # (preserves any item the user types, doesn't filter by
            # material vocabulary). Fall back to the picky parse_scope
            # only when the text has no blank-line block structure
            # (raw Trello paste with no separators).
            parsed = self._parse_scope_blocks(raw)
            if len(parsed) < 2 and "\n\n" not in raw:
                fallback = parse_scope(raw)
                if fallback:
                    parsed = fallback
            if not parsed:
                messagebox.showwarning("Not Parsed",
                    "Could not detect a room-by-room scope in that text.\n\n"
                    "Make sure each room name is on its own line, with the "
                    "scope items on the lines underneath, and a blank "
                    "line between rooms.", parent=dlg)
                return
            self._scope_rooms = parsed
            ems  = os.path.join(job_path, "EMS")
            base = ems if os.path.isdir(ems) else job_path
            docs = os.path.join(base, "DOCS")
            os.makedirs(docs, exist_ok=True)
            out  = os.path.join(docs, "Scope.pdf")
            try:
                build_scope_pdf(self._scope_rooms, self.insured, out)
            except Exception as ex:
                messagebox.showerror("PDF Error", str(ex), parent=dlg)
                return
            dlg.destroy()
            os.startfile(out)

        tk.Button(bot, text="Save PDF to EMS Docs",
                  font=("Segoe UI Variable", 10, "bold"),
                  bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                  relief="flat", padx=16, pady=6,
                  command=_save).pack(side="right")

    # ── Back ──────────────────────────────────────────────────────────────────
    def _back(self):
        self.frame_preview.pack_forget()
        self.frame_input.pack(fill="both", expand=True)
        self._set_step_title("EMS Snapshot")

    def _close_tool(self):
        """Close handler — embedded vs standalone behaves differently.

        When the snapshot is hosted inside the launcher, `self.destroy()`
        leaves a dead reference in `host._panels[key]`; the next time
        the user clicks the tool tab, the launcher tries to repaint a
        destroyed widget ("bad window path name"). Instead, ask the
        host to navigate back to whatever was previously shown.

        Standalone (no `host` attribute), the panel IS the window — so
        destroying it is the right move."""
        host = getattr(self, "host", None)
        if host is not None and hasattr(host, "_go_back"):
            try:
                host._go_back()
                return
            except Exception:
                pass
        # Standalone fallback (or host without history) — destroy as
        # the old behavior did.
        try:
            self.destroy()
        except Exception:
            pass

    # ── Generate PDF ──────────────────────────────────────────────────────────
    def _generate(self):
        sub_rows = [(v["date"].get(), v["weekday"].get(),
                     v["activity"].get(), v["techs"].get())
                    for v in self.sub_entries if v["date"].get().strip()]
        log_rows = [(v["date"].get(), v["weekday"].get(),
                     v["activity"].get(), v["techs"].get())
                    for v in self.log_entries if v["date"].get().strip()]

        if not log_rows:
            if not messagebox.askyesno(
                "No log entries",
                "The daily job log is empty — generate a blank PDF anyway?"):
                return

        # OneDrive sync-state warning. The audit + snapshot read files
        # off disk; if SP is still pulling content, the PDF / missing-
        # items capture will undercount. Surface before generation so
        # the user can let sync finish first.
        try:
            import persistence as _per
            import sp_sync_state as _sss
            _folder = _per.get_folder_path(self.insured) or ""
            if _folder:
                _sync = _sss.count_cloud_only(_folder)
                if _sync.get("unsynced", 0) > 0:
                    samples = _sync.get("samples") or []
                    sample_txt = (
                        "\n\nExamples:\n  " + "\n  ".join(samples[:6])
                        if samples else "")
                    if not messagebox.askyesno(
                        "OneDrive sync incomplete",
                        f"{_sync['unsynced']} of {_sync['total']} files in "
                        f"this folder are cloud-only — OneDrive hasn't "
                        f"pulled them down yet.{sample_txt}\n\n"
                        "Generating now may produce a snapshot with "
                        "incomplete data and trigger false 'missing' "
                        "comments on the Trello card.\n\n"
                        "Generate anyway?"):
                        return
        except Exception:
            pass

        # Commercial path: include the contact-person extra in the
        # header. self.insured is kept as the simple (folder-safe) name
        # everywhere else, so this is the only place the combined string
        # is constructed.
        ch = (getattr(self, "_customer_for_header", "") or "").strip()
        insured_header = f"{self.insured} — {ch}" if ch else self.insured
        data = {
            "insured_job":          insured_header,
            "carrier_claim":        self.carrier,
            "date_of_loss":         self.dol,
            "first_site_visit":     self.first_visit,
            "cause_category_class": self.cause,
            "subs_used":            "Y" if sub_rows else "N",
        }
        for i, (d, wd, act, tech) in enumerate(
                sub_rows[:SNAPSHOT_TEMPLATE_SUBS_MAX], 1):
            data[f"sub_date_{i}"]     = d
            data[f"sub_weekday_{i}"]  = wd
            data[f"sub_activity_{i}"] = act
            data[f"sub_techs_{i}"]    = tech
        for i, (d, wd, act, tech) in enumerate(
                log_rows[:SNAPSHOT_TEMPLATE_LOGS_MAX], 1):
            data[f"log_date_{i}"]     = d
            data[f"log_weekday_{i}"]  = wd
            data[f"log_activity_{i}"] = act
            data[f"log_techs_{i}"]    = tech

        # Strip Windows-illegal filename characters (\ / : * ? " < > |)
        # so an insured name with a date in it (e.g. "Unit 565 - 5/7/26")
        # doesn't get treated as a path with subdirectories. Pipe/colon
        # also matter for unit names like "Block A | 12:30 visit".
        safe_insured = re.sub(r'[\\/:*?"<>|]', "-",
                              (self.insured or "snapshot")).strip(" .-")
        if not safe_insured:
            safe_insured = "snapshot"
        output_path = os.path.join(OUTPUT_DIR, f"{safe_insured}.pdf")
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Background-thread the heavy lifting. fill_pdf + overflow
        # append + Excel mark_completed used to run on the UI thread,
        # freezing the panel for 3–6s while the user stared at an
        # unresponsive window. Now the UI shows a "Generating…" toast
        # immediately and finishes (open PDF + show audit) when the
        # worker reports back.
        sub_overflow = sub_rows[SNAPSHOT_TEMPLATE_SUBS_MAX:]
        log_overflow = log_rows[SNAPSHOT_TEMPLATE_LOGS_MAX:]
        # Disable the Generate button so a double-click can't fire two
        # parallel writes against the same PDF/Excel.
        try:
            if getattr(self, "_generate_btn", None) is not None:
                self._generate_btn.configure(state="disabled",
                                              text="Generating…")
        except Exception:
            pass
        try:
            show_toast(self, "Generating snapshot…", kind="info")
        except Exception:
            pass

        def _bg():
            err: Exception | None = None
            try:
                fill_pdf(data, output_path)
                if sub_overflow or log_overflow:
                    try:
                        append_overflow_pages(
                            output_path, sub_overflow, log_overflow,
                            insured=insured_header)
                    except Exception as ex:
                        try:
                            import ems_log
                            ems_log.warn("snapshot_gui",
                                          f"overflow append failed: {ex}")
                        except Exception:
                            pass
                # Best-effort side effects — never block PDF success.
                try:
                    self._append_trello_to_job_notes()
                except Exception:
                    pass
                # Tracker capture always runs (Hygiene needs the entries)
                # but never posts its own Trello comment now — the
                # snapshot preview dialog on the main thread handles the
                # single consolidated comment.
                try:
                    self._capture_missing_items_after_generate(
                        skip_trello_post=True)
                except Exception:
                    pass
                try:
                    import snapshots_excel as _sx
                    tol = ""
                    cause_blob = (self.cause or "").lower()
                    for key in ("water", "mold", "fire", "smoke",
                                 "bio", "asbestos", "lead",
                                 "storm", "vandalism"):
                        if key in cause_blob:
                            tol = key.capitalize()
                            break
                    _sx.mark_completed(self.insured,
                                         type_of_loss=tol or None)
                except Exception as ex:
                    try:
                        import ems_log
                        ems_log.warn("snapshot_gui",
                                      f"mark_completed failed: {ex}")
                    except Exception:
                        pass
            except Exception as ex:
                err = ex

            def _done():
                # Hard-fail-safe: snapshot tool may have been closed
                # while the worker was running. winfo_exists() on the
                # panel itself is the cheapest "are we still alive"
                # check — bail entirely if not.
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                try:
                    if getattr(self, "_generate_btn", None) is not None:
                        if self._generate_btn.winfo_exists():
                            self._generate_btn.configure(
                                state="normal", text="Generate")
                except Exception:
                    pass
                if err is not None:
                    try:
                        messagebox.showerror(
                            "Generate failed", str(err))
                    except Exception:
                        pass
                    return
                # Stash the path so the audit screen can surface a
                # ✓ saved banner + Open PDF button when the audit step
                # fails (folder not found, X: drive offline). Generation
                # has already succeeded by this point, so the user
                # should see that clearly instead of an audit error
                # message that looks like a generation failure.
                self._last_snapshot_pdf = output_path
                try:
                    os.startfile(output_path)
                except Exception:
                    pass
                # Mark the Trello card as drafted so the Hygiene
                # "📸 Ready for snapshot" section stops re-surfacing it
                # on subsequent scans. The user was seeing cards they'd
                # already snapshotted keep coming back because the
                # closeout-ready signals (lane membership, "ready for
                # snapshot" comment) both still match — only the
                # drafted flag filters them out. Generating a snapshot
                # is the strongest possible "done" signal; auto-marking
                # avoids the per-card manual click.
                try:
                    import persistence as _per
                    _cid = (_per.get_trello_card_id(self.insured)
                             or "") if self.insured else ""
                    if _cid:
                        import closeout_watcher as _cw
                        _cw.mark_drafted(_cid)
                except Exception:
                    pass
                try:
                    if self.winfo_exists():
                        self._show_audit()
                except Exception:
                    pass
                # Snapshot Trello preview — modal-on-main-thread so the
                # user can read + edit the comment before posting.
                # Sequenced after _show_audit so the preview lands on
                # top of the audit step, not the input form.
                #
                # Failures here used to be swallowed — leading to "the
                # snapshot comment isn't posting to Trello" with no
                # diagnostic. We log loudly + show a messagebox so the
                # user knows whether the preview was suppressed (e.g.
                # no card pinned) vs hard-erroring.
                try:
                    if self.winfo_exists():
                        shown = self._show_snapshot_trello_preview(
                            output_path)
                        if shown is False:
                            try:
                                show_toast(
                                    self,
                                    "Snapshot saved — Trello post skipped "
                                    "(no card pinned for this insured).",
                                    kind="warn", duration=4500)
                            except Exception:
                                pass
                except Exception as ex:
                    try:
                        import ems_log
                        ems_log.error(
                            "snapshot_gui",
                            f"Trello preview/post failed for "
                            f"{self.insured!r}: {ex}")
                    except Exception:
                        pass
                    try:
                        messagebox.showerror(
                            "Trello post failed",
                            "The snapshot PDF was generated, but the "
                            "Trello comment didn't post:\n\n"
                            f"{type(ex).__name__}: {ex}\n\n"
                            "You can still attach + comment manually from "
                            "the Trello card.")
                    except Exception:
                        pass
            try:
                self.after(0, _done)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _append_trello_to_job_notes(self):
        """Append the raw Trello-comments paste to this client's job-notes
        .md file under a dated section header. No-op if either the insured
        name or the comments are empty. Failures are swallowed; PDF
        generation must not depend on this side effect."""
        raw = (getattr(self, "_raw_comments", "") or "").strip()
        insured = (self.insured or "").strip()
        if not raw or not insured:
            return
        try:
            import re as _re
            year = datetime.today().year
            # Pull a 4-digit year from the DOL string, else parse the YY
            # in M/D/YY format.
            m4 = _re.search(r'\b(\d{4})\b', self.dol or "")
            if m4:
                year = int(m4.group(1))
            else:
                m2 = _re.search(r'\b\d{1,2}/\d{1,2}/(\d{2})\b', self.dol or "")
                if m2:
                    year = 2000 + int(m2.group(1))

            from job_notes_gui import load_note, save_note
            existing = load_note(year, insured)
            stamp = datetime.now().strftime("%m-%d-%Y %H:%M")
            section = (f"## Trello notes — imported from EMS Snapshot "
                       f"{stamp}\n\n{raw}\n")
            new_text = (existing.rstrip() + "\n\n" + section
                        if existing.strip() else section)
            save_note(year, insured, new_text)
            try:
                show_toast(self, f"Trello notes added to {insured}'s job notes",
                           kind="success", duration=2200)
            except Exception:
                pass
        except Exception as ex:
            try:
                import ems_log
                ems_log.warn("snapshot",
                    f"append trello → job notes failed for {insured!r}: {ex}")
            except Exception:
                pass

    def _build_snapshot_trello_body(self, pdf_path: str):
        """Compute the data the Trello preview dialog needs:
        (card_id, default_body, missing_labels). Returns None when no
        Trello card is pinned to the current insured (no card → no
        Trello workflow).

        Pure read — does NOT touch Trello. Safe to run on either the
        worker or the main thread."""
        insured = (self.insured or "").strip()
        if not insured or not pdf_path or not os.path.isfile(pdf_path):
            return None
        try:
            import persistence as per
        except Exception:
            return None
        try:
            card_id = per.get_trello_card_id(insured) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return None

        # Re-run the same missing-items detection the tracker uses so
        # the preview body matches what Hygiene will record.
        missing_labels: list[str] = []
        try:
            import audit_logic
            job_path = per.get_folder_path(insured) or ""
            if not job_path or not os.path.isdir(job_path):
                try:
                    base = AUDIT_BASE
                    year = datetime.today().year
                    year_folder = os.path.join(base, f"{year} Jobs")
                    if os.path.isdir(year_folder):
                        def _norm(s):
                            return ((s or "").lower()
                                     .replace(",", "").strip())
                        target = _norm(insured)
                        for d in os.listdir(year_folder):
                            if _norm(d) == target or (
                                    len(target) >= 4
                                    and target in _norm(d)):
                                job_path = os.path.join(year_folder, d)
                                break
                except Exception:
                    job_path = ""
            if job_path and os.path.isdir(job_path):
                ems = os.path.join(job_path, "EMS")
                base_for_check = (ems if os.path.isdir(ems) else job_path)
                try:
                    form_issues = (audit_logic.check_forms(base_for_check)
                                    or [])
                except Exception:
                    form_issues = []
                for issue in form_issues:
                    if issue and str(issue) not in missing_labels:
                        missing_labels.append(str(issue))
                pics_root = os.path.join(base_for_check, "PICS")
                if os.path.isdir(pics_root):
                    for label, sub in (("Initial photos", "Initial"),
                                         ("Demo photos",    "Demo"),
                                         ("Final photos",   "Final")):
                        sub_path = os.path.join(pics_root, sub)
                        if not os.path.isdir(sub_path):
                            continue
                        try:
                            with os.scandir(sub_path) as it:
                                has_any = any(
                                    e.is_file()
                                    and not e.name.startswith(".")
                                    for e in it)
                        except OSError:
                            has_any = True
                        if (not has_any
                                and label not in missing_labels):
                            missing_labels.append(label)
        except Exception:
            missing_labels = []

        # Tech @mention from the card desc.
        tech_mention = ""
        try:
            import trello_client as tc
            card = tc.get_card(card_id)
            fields = tc.parse_card_desc(card.get("desc") or "")
            job = fields.get("JOB INFO") or {}
            initials = (job.get("TECH INITIALS")
                          or job.get("TECH") or "").strip()
            if initials:
                try:
                    import tech_roster as tr
                    h = tr.trello_handle_for(initials)
                    if h:
                        tech_mention = (h if h.startswith("@")
                                          else f"@{h}")
                except Exception:
                    tech_mention = f"@{initials}"
        except Exception:
            tech_mention = ""

        lines: list[str] = [
            "📸 Snapshot completed — see attached PDF."]
        if missing_labels:
            lines.append("")
            lines.append("⚠ Missing items: "
                         + ", ".join(missing_labels) + ".")
            if tech_mention:
                lines.append(f"{tech_mention} please upload to the "
                             "appropriate folder when possible.")
            else:
                lines.append("Please upload to the appropriate folder "
                             "when possible.")
            lines.append("Tracked in Hygiene until resolved.")
        else:
            lines.append("All paperwork and photo folders accounted for.")
        body = "\n".join(lines)
        return {
            "card_id":        card_id,
            "body":           body,
            "missing_labels": missing_labels,
        }

    def _show_snapshot_trello_preview(self, pdf_path: str) -> bool:
        """Pop a modal preview of the Trello comment that will be
        posted alongside the snapshot PDF attachment. Lets the user
        edit the body before approving, or skip the Trello post
        entirely. Runs on the main thread.

        Returns True when the preview was shown, False when it was
        suppressed (no Trello card pinned to this insured, or no PDF
        on disk to attach). The caller surfaces the False case as a
        toast so the user knows why nothing posted."""
        ctx = self._build_snapshot_trello_body(pdf_path)
        if not ctx:
            # No card pinned (or missing PDF). Tell the caller so it
            # can surface a toast — the previous silent no-op left the
            # user with a snapshot PDF and no idea why no Trello
            # comment ever showed up.
            try:
                import ems_log
                ems_log.warn(
                    "snapshot_gui",
                    f"Trello preview suppressed for {self.insured!r}: "
                    "no Trello card pinned (or PDF missing).")
            except Exception:
                pass
            return False

        insured = (self.insured or "").strip()
        try:
            size_bytes = os.path.getsize(pdf_path)
            size_label = (
                f"{size_bytes / 1024 / 1024:.1f} MB"
                if size_bytes >= 1024 * 1024
                else f"{size_bytes / 1024:.0f} KB")
        except OSError:
            size_label = ""
        pdf_name = f"{insured} Snapshot.pdf"

        dlg = tk.Toplevel(self)
        dlg.title("Post snapshot to Trello?")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("560x540")
        except tk.TclError:
            pass

        # Header
        hdr = tk.Frame(dlg, bg=BG, padx=18, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📤 Post snapshot to Trello",
                 font=("Fraunces", 16, "bold"),
                 bg=BG, fg=TEXT_DARK, anchor="w"
                 ).pack(fill="x")
        tk.Label(hdr, text=insured,
                 font=("Segoe UI Variable", 11),
                 bg=BG, fg=TEXT_GRAY, anchor="w"
                 ).pack(fill="x", pady=(2, 0))
        att_line = f"📎 Will attach: {pdf_name}"
        if size_label:
            att_line += f"  ·  {size_label}"
        tk.Label(hdr, text=att_line,
                 font=("Segoe UI Variable", 9),
                 bg=BG, fg=TEXT_GRAY, anchor="w"
                 ).pack(fill="x", pady=(6, 0))
        if ctx["missing_labels"]:
            try:
                from ui_buttons import chip_label
                chip_label(
                    hdr,
                    f"⚠ {len(ctx['missing_labels'])} missing flagged",
                    kind="warn").pack(anchor="w", pady=(6, 0))
            except Exception:
                pass
        else:
            try:
                from ui_buttons import chip_label
                chip_label(hdr, "✓ All items accounted for",
                           kind="ok").pack(anchor="w", pady=(6, 0))
            except Exception:
                pass

        # Editable comment body
        body_frame = tk.Frame(dlg, bg=WHITE, padx=14, pady=12)
        body_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        tk.Label(body_frame, text="Comment body (editable)",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w"
                 ).pack(fill="x", pady=(0, 6))
        txt_wrap = tk.Frame(body_frame, bg=WHITE)
        txt_wrap.pack(fill="both", expand=True)
        txt = tk.Text(txt_wrap, wrap="word",
                       font=("Segoe UI Variable", 10),
                       bg=SURFACE_2, fg=TEXT_DARK,
                       insertbackground=TEXT_DARK,
                       relief="flat", padx=10, pady=8,
                       highlightthickness=1,
                       highlightbackground=BORDER)
        sb = tk.Scrollbar(txt_wrap, orient="vertical",
                            command=txt.yview)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(sb)
        except Exception:
            pass
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", ctx["body"])

        tk.Label(body_frame,
                 text="Edit freely — what you see here is what gets "
                      "posted. Empty body = no comment, attachment "
                      "only.",
                 font=("Segoe UI Variable", 8),
                 bg=WHITE, fg=TEXT_GRAY, anchor="w",
                 wraplength=500, justify="left"
                 ).pack(fill="x", pady=(6, 0))

        # Footer
        bot = tk.Frame(dlg, bg=BG, padx=18, pady=12)
        bot.pack(fill="x", side="bottom")

        # Track the user's choice so we can post (or not) once the
        # dialog closes. `captured_body` is filled by _approve BEFORE
        # the dialog destroys — reading txt.get() after dlg.destroy()
        # raises TclError because the Text widget is gone by then
        # (Tk destroys children with their parent).
        approved = [False]
        captured_body: list[str] = [""]

        def _approve():
            try:
                captured_body[0] = (
                    txt.get("1.0", "end") or "").strip()
            except tk.TclError:
                captured_body[0] = ""
            approved[0] = True
            dlg.destroy()

        def _skip():
            approved[0] = False
            dlg.destroy()

        try:
            from ui_buttons import done_button, secondary_button
            secondary_button(
                bot, "Skip Trello (PDF only)",
                command=_skip).pack(side="right", padx=(6, 0))
            done_button(
                bot, "📤 Post to Trello",
                command=_approve).pack(side="right")
        except Exception:
            tk.Button(bot, text="Skip Trello",
                      bg=SURFACE_2, fg=TEXT_DARK, relief="flat",
                      padx=10, pady=4, cursor="hand2",
                      command=_skip).pack(side="right", padx=(6, 0))
            tk.Button(bot, text="📤 Post to Trello",
                      bg=GREEN, fg=ON_ACCENT, relief="flat",
                      padx=10, pady=4, cursor="hand2",
                      command=_approve).pack(side="right")

        # Center on parent
        try:
            dlg.update_idletasks()
            px = self.winfo_rootx() + (self.winfo_width() // 2)
            py = self.winfo_rooty() + (self.winfo_height() // 2)
            dw = dlg.winfo_width()
            dh = dlg.winfo_height()
            dlg.geometry(f"+{px - dw // 2}+{py - dh // 2}")
        except tk.TclError:
            pass
        dlg.wait_window()

        if not approved[0]:
            try:
                import ems_log
                ems_log.warn(
                    "snapshot_gui",
                    f"Trello post skipped by user for {self.insured!r}")
            except Exception:
                pass
            return True

        # Final body the user signed off on (possibly edited).
        # Captured BEFORE dlg.destroy() inside _approve — reading
        # txt.get() here would TclError, because Tk destroys the Text
        # widget along with its parent dialog.
        final_body = captured_body[0]
        card_id = ctx["card_id"]
        missing_count = len(ctx["missing_labels"])

        # Network I/O moves to a daemon thread so the UI stays
        # responsive while the upload runs. Toast on completion.
        # Errors caught from tc.attach_file / tc.post_comment are
        # captured (rather than re-raised) so the UI thread can
        # decide what to toast — but they're ALSO logged with the
        # exception text so "the snapshot comment isn't posting"
        # has a paper trail next time.
        def _post_worker():
            try:
                import trello_client as tc
            except Exception as ex:
                try:
                    import ems_log
                    ems_log.error(
                        "snapshot_gui",
                        f"trello_client import failed: {ex}")
                except Exception:
                    pass
                return
            # Step 1 — attach the PDF first and capture the resulting
            # attachment URL. Trello's UI renders a URL in a comment as
            # an inline preview when that URL points to one of the
            # card's own attachments — which lets us collapse the
            # previously-separate "attached PDF" + "posted comment"
            # entries into ONE rich comment with the file embedded.
            # Without prepending the URL, the comment and attachment
            # show as two separate items in the card's activity feed.
            attach_ok = False
            attach_err = ""
            attach_url = ""
            try:
                att = tc.attach_file(
                    card_id, pdf_path,
                    name=pdf_name)
                attach_ok = bool(att)
                if att:
                    attach_url = (att.get("url") or "").strip()
                if not attach_ok:
                    attach_err = (
                        "tc.attach_file returned None — usually a "
                        "Trello auth issue, oversize PDF, or the "
                        "card_id is no longer valid.")
            except Exception as ex:
                attach_err = f"{type(ex).__name__}: {ex}"
            if attach_err:
                try:
                    import ems_log
                    ems_log.error(
                        "snapshot_gui",
                        f"attach_file failed (card={card_id} "
                        f"insured={self.insured!r}): {attach_err}")
                except Exception:
                    pass
            comment_ok = False
            comment_err = ""
            # Embed the attachment URL at the top of the comment so
            # Trello renders the PDF preview inline with the message.
            # When the attach failed (no URL) we fall back to the bare
            # message — separate-items behavior, but still post.
            body_with_attachment = final_body or ""
            if attach_url and body_with_attachment:
                body_with_attachment = (
                    f"{attach_url}\n\n{body_with_attachment}")
            elif attach_url and not body_with_attachment:
                body_with_attachment = attach_url
            if body_with_attachment:
                try:
                    res = tc.post_comment(card_id, body_with_attachment)
                    comment_ok = bool(res)
                    if not comment_ok:
                        comment_err = (
                            "tc.post_comment returned None — empty body "
                            "or Trello rejected the POST.")
                except Exception as ex:
                    comment_err = f"{type(ex).__name__}: {ex}"
                if comment_err:
                    try:
                        import ems_log
                        ems_log.error(
                            "snapshot_gui",
                            f"post_comment failed (card={card_id} "
                            f"insured={self.insured!r}): {comment_err}")
                    except Exception:
                        pass

            def _toast():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                try:
                    if attach_ok and (comment_ok or not final_body):
                        bits = ["Posted snapshot to Trello"]
                        if missing_count:
                            bits.append(f"({missing_count} missing flagged)")
                        elif not final_body:
                            bits.append("(attachment only)")
                        show_toast(self, " ".join(bits),
                                   kind="success", duration=3000)
                    elif comment_ok:
                        show_toast(
                            self,
                            "Posted comment but PDF attach failed — "
                            f"{attach_err or 'see EMS log'}",
                            kind="warn", duration=6000)
                    elif attach_ok:
                        show_toast(
                            self,
                            "Attached PDF but comment post failed — "
                            f"{comment_err or 'see EMS log'}",
                            kind="warn", duration=6000)
                    else:
                        # Both failed — escalate to a messagebox so the
                        # user knows the snapshot didn't reach Trello at
                        # all, and gets the actual error text rather
                        # than a vanishing toast.
                        try:
                            messagebox.showerror(
                                "Trello post failed",
                                "Neither the PDF attachment nor the "
                                "comment posted to Trello.\n\n"
                                f"Attach: {attach_err or 'unknown'}\n"
                                f"Comment: {comment_err or 'unknown'}\n\n"
                                "The snapshot PDF was still saved "
                                "locally.")
                        except Exception:
                            show_toast(
                                self,
                                "Trello post failed — PDF saved "
                                f"locally only. {attach_err or ''}",
                                kind="warn", duration=6000)
                except Exception:
                    pass
            try:
                self.after(0, _toast)
            except Exception:
                pass

        threading.Thread(target=_post_worker, daemon=True).start()

    def _open_flag_missing_for_row(self, client, card_id=""):
        """Pop the shared "Flag missing item" dialog scoped to ONE
        audit row (not the snapshot's loaded insured). Mirrors the
        Run Audit / IUQ per-row flag buttons so the affordance is
        identical across the three tools. Stage tag is "audit".
        """
        client = (client or "").strip()
        if not client:
            return
        if not card_id:
            try:
                card_id = persistence.get_trello_card_id(client) or ""
            except Exception:
                card_id = ""
        tech_initials = ""
        if card_id:
            try:
                import trello_client as tc
                card = tc.get_card(card_id)
                if card:
                    fields = tc.parse_card_desc(card.get("desc") or "")
                    job = fields.get("JOB INFO") or {}
                    tech_initials = (job.get("TECH INITIALS")
                                     or job.get("TECH") or "").strip()
            except Exception:
                pass
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

    def _open_flag_missing_dialog(self):
        """Pop the shared flag dialog scoped to the current insured.
        Uses stage='snapshot' so the Trello note + Hygiene chip
        attribute the gap to the snapshot step (matches what the
        auto-capture after generate() does)."""
        insured = (self.insured or "").strip()
        if not insured:
            messagebox.showinfo(
                "No insured", "Pick a Trello card or parse comments "
                "first so we know which job to flag.", parent=self)
            return
        card_id = ""
        try:
            import persistence as per
            card_id = per.get_trello_card_id(insured) or ""
        except Exception:
            card_id = ""
        tech_initials = ""
        if card_id:
            try:
                import trello_client as tc
                card = tc.get_card(card_id)
                fields = tc.parse_card_desc(card.get("desc") or "")
                job = fields.get("JOB INFO") or {}
                tech_initials = (job.get("TECH INITIALS")
                                 or job.get("TECH") or "").strip()
            except Exception:
                pass
        try:
            from flag_missing_dialog import open_flag_dialog
        except Exception as ex:
            messagebox.showerror("Flag dialog unavailable",
                                   f"Couldn't load module:\n{ex}",
                                   parent=self)
            return
        open_flag_dialog(
            self,
            client=insured,
            card_id=card_id,
            card_url=(f"https://trello.com/c/{card_id}"
                      if card_id else ""),
            tech_initials=tech_initials,
            stage="snapshot",
        )

    def _capture_missing_items_after_generate(self, *,
                                                 skip_trello_post=False):
        """Right after the PDF is written, scan the resolved job folder
        for missing forms + photos. Each gap becomes a tracked entry
        in missing_items_tracker.

        `skip_trello_post=True` tells the tracker NOT to post its own
        per-call comment — used when `_attach_snapshot_to_trello_card`
        already posted one consolidated comment listing the same items
        (avoids two parallel Trello notifications saying the same
        thing). Hygiene still picks up the tracked entries either way.

        Resolution order for the job path:
          1. persistence.get_folder_path(insured)  — pinned via audit /
             Find Folder / right-click Change Folder
          2. fallback: walk the year-Jobs directory for a fuzzy match
             (same `_find_path` heuristic the scope dialog uses)

        Silent failure: missing-items capture is observability, not
        load-bearing. A locked persistence file or a missing audit_logic
        import shouldn't surface to the user mid-generate."""
        insured = (self.insured or "").strip()
        if not insured:
            return
        try:
            import persistence as per
            import audit_logic
            import missing_items_tracker as mit

            job_path = per.get_folder_path(insured) or ""
            if not job_path or not os.path.isdir(job_path):
                # Fall back to the same year-folder walk the scope
                # dialog uses, so the capture works even when no
                # explicit folder pin exists.
                try:
                    base = AUDIT_BASE
                    year = datetime.today().year
                    year_folder = os.path.join(base, f"{year} Jobs")
                    if os.path.isdir(year_folder):
                        def _norm(s):
                            return (s or "").lower().replace(",", "").strip()
                        target = _norm(insured)
                        for d in os.listdir(year_folder):
                            if _norm(d) == target or (
                                    len(target) >= 4 and target in _norm(d)):
                                job_path = os.path.join(year_folder, d)
                                break
                except Exception:
                    job_path = ""

            if not job_path or not os.path.isdir(job_path):
                return

            # Run the audit's form-check against the EMS subtree.
            ems = os.path.join(job_path, "EMS")
            base_for_check = ems if os.path.isdir(ems) else job_path
            missing: list[str] = []
            try:
                form_issues = audit_logic.check_forms(base_for_check) or []
            except Exception:
                form_issues = []
            for issue in form_issues:
                # check_forms returns short labels like "ATP", "CIF",
                # "Scope" — pass through; the tracker canonicalizes.
                if not issue:
                    continue
                key = str(issue).strip().lower().replace(" ", "_")
                if key not in missing:
                    missing.append(key)

            # Photo presence check — initial/demo/final folders empty
            # = missing photos of that type. Cheap directory existence
            # + emptiness check; we don't enumerate every file.
            pics_root = os.path.join(base_for_check, "PICS")
            if os.path.isdir(pics_root):
                photo_buckets = {
                    "initial_photos": "Initial",
                    "demo_photos":    "Demo",
                    "final_photos":   "Final",
                }
                for key, sub in photo_buckets.items():
                    sub_path = os.path.join(pics_root, sub)
                    if not os.path.isdir(sub_path):
                        continue
                    try:
                        # Empty = no images of any extension. The audit
                        # logic has richer detection; we keep this
                        # capture light so generate() stays fast.
                        with os.scandir(sub_path) as it:
                            has_any = any(
                                e.is_file() and not e.name.startswith(".")
                                for e in it)
                    except OSError:
                        has_any = True   # assume present rather than nag
                    if not has_any and key not in missing:
                        missing.append(key)

            if not missing:
                return

            # Tech initials — pull from the pinned Trello card desc when
            # available so the comment @mentions the responsible tech.
            tech_initials = ""
            try:
                card_id = per.get_trello_card_id(insured) or ""
                if card_id:
                    import trello_client as tc
                    card = tc.get_card(card_id)
                    fields = tc.parse_card_desc(card.get("desc") or "")
                    job = fields.get("JOB INFO") or {}
                    tech_initials = (job.get("TECH INITIALS")
                                     or job.get("TECH")
                                     or "").strip()
            except Exception:
                tech_initials = ""

            try:
                card_id = per.get_trello_card_id(insured) or ""
            except Exception:
                card_id = ""
            try:
                card_url = (f"https://trello.com/c/{card_id}"
                            if card_id else "")
            except Exception:
                card_url = ""

            mit.capture_missing_items(
                insured, card_id=card_id, card_url=card_url,
                missing=missing, tech_initials=tech_initials,
                post_comment=(not skip_trello_post))
            try:
                show_toast(
                    self,
                    f"Tracking {len(missing)} missing item(s) for "
                    f"{insured} — see Hygiene → Missing items",
                    kind="info", duration=3000)
            except Exception:
                pass
        except Exception as ex:
            try:
                import ems_log
                ems_log.warn(
                    "snapshot",
                    f"capture_missing_items failed for {insured!r}: {ex}")
            except Exception:
                pass


def main(argv=None):
    run_standalone(SnapshotApp, geometry="740x640")


if __name__ == "__main__":
    main()
