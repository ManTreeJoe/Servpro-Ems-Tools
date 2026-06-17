"""
New EMS Job — creates the standard subfolder structure inside an existing
client job folder. Year + client folders must already exist; this tool only
adds the CONTENTS / EMS subfolders underneath.
"""
import os
import re
import sys
from datetime import datetime
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctk_helpers as ctkh
import paths
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    TEXT_MUTED, BORDER, FLAG_RED, SURFACE_2,
                    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER, WARN_FG)
from tool_panel import (ToolPanel, run_standalone, show_toast,
                         ScrollableFrame, ResponsiveSnap)
from ui_buttons import icon_button

AUDIT_BASE = paths.audit_base()
_ICON = paths.resource("wrench.ico")

SECTIONS    = ["CONTENTS", "EMS"]    # RECON intentionally omitted — Recon team handles their own
SUBFOLDERS  = ["DOCS", "PICS", "FIELD DOCS"]


def _subfolder_paths(sections):
    """Cross product of selected sections × DOCS/PICS/FIELD DOCS."""
    out = []
    for s in sections:
        for sub in SUBFOLDERS:
            out.append(os.path.join(s, sub))
    return out


# ── Helpers ──────────────────────────────────────────────────────────────────

def _open_folder(path):
    try:
        if path and os.path.isdir(path):
            os.startfile(path)
    except OSError:
        pass


def _normalize(s):
    s = re.sub(r"[^a-zA-Z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _fuzzy_match(query, candidates, top_n=5):
    q_words = set(_normalize(query).split())
    if not q_words:
        return []
    scored = []
    for c in candidates:
        c_words = set(_normalize(c).split())
        shared = len(q_words & c_words)
        if shared:
            scored.append((c, shared))
    scored.sort(key=lambda x: (-x[1], x[0].lower()))
    return scored[:top_n]


def _find_year_folder(base, year, la_fire):
    if not os.path.isdir(base):
        return None, f"Cannot access {base} — is the X: drive connected?"
    try:
        with os.scandir(base) as it:
            entries = [e for e in it if e.is_dir()]
    except OSError as ex:
        return None, str(ex)

    year_str = str(year)
    for e in entries:
        upper = e.name.upper()
        is_la = ("LA" in upper) and ("FIRE" in upper)
        if year_str not in e.name:
            continue
        if la_fire and is_la:
            return e.path, None
        if not la_fire and not is_la:
            return e.path, None

    tag = "LA Fire " if la_fire else ""
    return None, f"No {tag}{year} folder found in {base}"


def _find_client_match(year_path, client_name):
    """Returns (exact_match_name | None, fuzzy_matches: [(name, score), ...])."""
    try:
        with os.scandir(year_path) as it:
            candidates = [e.name for e in it if e.is_dir()]
    except OSError:
        candidates = []

    norm_q = _normalize(client_name)
    for c in candidates:
        if _normalize(c) == norm_q:
            return c, []

    parts = client_name.strip().split()
    if len(parts) > 1:
        reversed_q = _normalize(" ".join(reversed(parts)))
        for c in candidates:
            if _normalize(c) == reversed_q:
                return c, []

    return None, _fuzzy_match(client_name, candidates)


def _create_subfolders(client_path, sections):
    """Returns (created_count, [{rel, created, path}, ...]) for the requested sections."""
    results = []
    created = 0
    for rel in _subfolder_paths(sections):
        full = os.path.join(client_path, rel)
        if os.path.isdir(full):
            results.append({"rel": rel, "created": False, "path": full})
        else:
            os.makedirs(full, exist_ok=True)
            results.append({"rel": rel, "created": True, "path": full})
            created += 1
    return created, results


# ── Panel ────────────────────────────────────────────────────────────────────

class NewJobApp(ToolPanel):
    TOOL_TITLE = "New EMS Job"
    TOOL_AUMID = "Servpro.EMS.NewJob"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("New EMS Job")
        self.geometry("900x680")
        self.minsize(720, 520)
        self.configure(bg=BG)
        if os.path.isfile(_ICON):
            try:
                self.iconbitmap(default=_ICON)
                self.iconbitmap(_ICON)
            except Exception:
                pass

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.build_header("SERVPRO  ·  New EMS Job",
                          subtitle="Create the standard subfolder structure for a client",
                          pady=10)

        # Form card
        card = ctkh.card(self)
        card.pack(fill="x", padx=20, pady=(16, 10))

        inner = tk.Frame(card, bg=WHITE, padx=18, pady=14)
        inner.pack(fill="x")

        # Client name
        ctkh.h2(inner, "Client name", fg_color=WHITE).grid(
            row=0, column=0, sticky="w")
        ctkh.ctk.CTkLabel(
            inner,
            text="(Last First, First Last, etc. — fuzzy match if not exact)",
            font=ctkh.font(9), text_color=TEXT_GRAY, fg_color=WHITE
        ).grid(row=0, column=1, columnspan=3, sticky="w", padx=(8, 0))

        self._name_var = tk.StringVar()
        ent = ctkh.entry(inner, textvariable=self._name_var,
                         font=ctkh.font(12), height=36)
        ent.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 12))
        ent.bind("<Return>", lambda e: self._find_and_create())
        self._name_entry = ent

        # Year + LA Fire + Submit button — all on one row
        ctkh.h2(inner, "Year", fg_color=WHITE).grid(
            row=2, column=0, sticky="w")
        self._year_var = tk.IntVar(value=datetime.now().year)
        # Spinbox has no CTk equivalent; styled tk.Spinbox is fine.
        tk.Spinbox(inner, from_=2020, to=2099, textvariable=self._year_var,
                   font=("Segoe UI Variable", 11), width=8, relief="solid", bd=1
                   ).grid(row=3, column=0, sticky="w", pady=(2, 0))

        self._la_var = tk.BooleanVar(value=False)
        ctkh.ctk.CTkSwitch(inner, text="LA Fire job", variable=self._la_var,
                           font=ctkh.font(10), text_color=TEXT_DARK,
                           progress_color=GREEN, button_color=WHITE,
                           button_hover_color="#F0F0F0", fg_color=WHITE
                           ).grid(row=3, column=1, sticky="w",
                                  padx=(20, 0), pady=(2, 0))

        self._find_btn = ctkh.btn(
            inner, "🔎  Find Job Folder", command=self._find_and_create,
            kind="primary", height=36)
        # Default: right side of the Year/LA-Fire row. _layout_find_btn
        # below moves it to a full-width row when the form is narrow so
        # it can't get cut off the right edge.
        self._find_btn.grid(row=3, column=3, sticky="e", pady=(2, 0))
        self._find_btn_inline = True

        def _layout_find_btn(_e=None):
            try:
                w = card.winfo_width()
            except tk.TclError:
                return
            if w <= 1:
                return
            want_inline = w >= 520
            if want_inline and not self._find_btn_inline:
                self._find_btn.grid_forget()
                self._find_btn.grid(row=3, column=3, sticky="e",
                                     pady=(2, 0))
                self._find_btn_inline = True
            elif (not want_inline) and self._find_btn_inline:
                self._find_btn.grid_forget()
                self._find_btn.grid(row=6, column=0, columnspan=4,
                                     sticky="ew", pady=(10, 0))
                self._find_btn_inline = False
        # Debounce — Configure fires per-pixel during a drag-resize.
        self._find_btn_after = None
        def _on_card_configure(_e=None):
            if self._find_btn_after is not None:
                try: self.after_cancel(self._find_btn_after)
                except Exception: pass
            self._find_btn_after = self.after(40, _layout_find_btn)
        card.bind("<Configure>", _on_card_configure, add="+")

        # Section selector — which subfolder trees to build (only used when
        # creating a new client folder or adding missing subfolders)
        ctkh.h2(inner, "Sections to build", fg_color=WHITE).grid(
            row=4, column=0, sticky="w", pady=(14, 4))
        ctkh.ctk.CTkLabel(
            inner, text="Used only when you choose to create folders.",
            font=ctkh.font(9), text_color=TEXT_GRAY, fg_color=WHITE
        ).grid(row=4, column=1, columnspan=3, sticky="w",
               padx=(8, 0), pady=(14, 4))

        sec_row = tk.Frame(inner, bg=WHITE)
        sec_row.grid(row=5, column=0, columnspan=4, sticky="w")
        self._section_vars = {}
        for sec in SECTIONS:
            v = tk.BooleanVar(value=True)
            self._section_vars[sec] = v
            ctkh.ctk.CTkCheckBox(sec_row, text=sec, variable=v,
                                 font=ctkh.font(10, "bold"),
                                 text_color=TEXT_DARK, fg_color=GREEN,
                                 hover_color=GREEN_DARK,
                                 border_color=BORDER,
                                 corner_radius=4, checkbox_height=18,
                                 checkbox_width=18
                                 ).pack(side="left", padx=(0, 18))

        inner.columnconfigure(2, weight=1)

        # Output area card
        out_card = ctkh.card(self)
        out_card.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        ohdr = ctkh.ctk.CTkFrame(out_card, fg_color="#E8F5EE",
                                 corner_radius=0, height=32)
        ohdr.pack(fill="x")
        ohdr.pack_propagate(False)
        self._out_title = ctkh.ctk.CTkLabel(
            ohdr, text="Result", font=ctkh.font(10, "bold"),
            text_color=GREEN_DARK, fg_color="#E8F5EE")
        self._out_title.pack(side="left", padx=12, pady=4)

        # Scrollable inner
        scroll = ScrollableFrame(out_card, bg=WHITE)
        scroll.pack(fill="both", expand=True)
        self._out_inner   = scroll.inner
        self._out_scroll  = scroll

        self._show_idle()

    # ── State views ─────────────────────────────────────────────────────────
    def _clear_output(self):
        for w in self._out_inner.winfo_children():
            w.destroy()

    def _show_idle(self):
        self._clear_output()
        self._out_title.configure(text="Result", text_color=GREEN_DARK)
        msg = tk.Frame(self._out_inner, bg=WHITE)
        msg.pack(expand=True, fill="both", pady=40)
        tk.Label(msg, text="➕", font=("Segoe UI Variable", 36),
                 bg=WHITE, fg=TEXT_MUTED).pack()
        tk.Label(msg, text="Enter a client name above to begin.",
                 font=("Segoe UI Variable", 10), bg=WHITE, fg=TEXT_GRAY).pack(pady=(6, 0))
        tk.Label(msg, text=f"Looking under: {AUDIT_BASE}",
                 font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_MUTED).pack(pady=(2, 0))

    def _show_error(self, msg):
        self._clear_output()
        self._out_title.configure(text="Error", text_color=FLAG_RED)
        wrap = tk.Frame(self._out_inner, bg=WHITE, padx=16, pady=14)
        wrap.pack(fill="x", anchor="w")
        tk.Label(wrap, text="✕", font=("Segoe UI Variable", 22, "bold"),
                 bg=WHITE, fg=FLAG_RED).pack(side="left", padx=(0, 12))
        tk.Label(wrap, text=msg, font=("Segoe UI Variable", 10),
                 bg=WHITE, fg=TEXT_DARK,
                 wraplength=620, justify="left").pack(side="left", anchor="w")

    def _show_result(self, client_name, client_path, created, results, is_new=False):
        self._clear_output()
        if is_new:
            title = f"New job created — {client_name}"
        elif created:
            title = f"Done — {created} folder(s) created"
        else:
            title = "All folders already existed"
        self._out_title.configure(text=title, text_color=GREEN_DARK)

        head = tk.Frame(self._out_inner, bg=WHITE, padx=16, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="✓", font=("Segoe UI Variable", 22, "bold"),
                 bg=WHITE, fg=GREEN_DARK).pack(side="left", padx=(0, 12))
        info = tk.Frame(head, bg=WHITE)
        info.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(info, bg=WHITE)
        name_row.pack(anchor="w", fill="x")
        tk.Label(name_row, text=client_name, font=("Segoe UI Variable", 12, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w").pack(side="left")
        if is_new:
            tk.Label(name_row, text="  NEW",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=SUCCESS_BG, fg=SUCCESS_FG,
                     padx=6, pady=1).pack(side="left", padx=(8, 0))
        tk.Label(info, text=client_path, font=("Segoe UI Variable", 8),
                 bg=WHITE, fg=TEXT_GRAY, anchor="w").pack(anchor="w")
        ctkh.btn(head, "📁  Open job folder",
                 command=lambda: _open_folder(client_path),
                 kind="subtle", width=160).pack(side="right")

        ctkh.divider(self._out_inner).pack(fill="x", padx=16)

        list_box = tk.Frame(self._out_inner, bg=WHITE, padx=16, pady=10)
        list_box.pack(fill="x")
        for r in results:
            row = tk.Frame(list_box, bg=WHITE)
            row.pack(fill="x", pady=2)
            if r["created"]:
                badge_text, badge_fg, badge_bg = "+ NEW",  GREEN_DARK, "#DAF1E2"
            else:
                badge_text, badge_fg, badge_bg = "exists", TEXT_GRAY, "#F0F0F0"
            tk.Label(row, text=badge_text, font=("Segoe UI Variable", 8, "bold"),
                     bg=badge_bg, fg=badge_fg, padx=6, pady=1, width=7
                     ).pack(side="left")
            tk.Label(row, text=r["rel"], font=("Segoe UI Variable", 9),
                     bg=WHITE, fg=TEXT_DARK).pack(side="left", padx=(8, 0))
            icon_button(row, "📁", fg=TEXT_GRAY, hover=SUCCESS_HOVER,
                         padx=4, pady=0,
                         command=lambda p=r["path"]: _open_folder(p),
                         tooltip="Open job folder"
                         ).pack(side="left")

    # ── Action ──────────────────────────────────────────────────────────────
    def _selected_sections(self):
        return [s for s in SECTIONS if self._section_vars[s].get()]

    def _find_and_create(self):
        name = self._name_var.get().strip()
        if not name:
            self._show_error("Enter a client name first.")
            self._name_entry.focus_set()
            return

        try:
            year = int(self._year_var.get())
        except (tk.TclError, ValueError):
            self._show_error("Year must be a number.")
            return

        la_fire = self._la_var.get()

        year_path, err = _find_year_folder(AUDIT_BASE, year, la_fire)
        if err:
            self._show_error(err)
            return

        match, fuzzy = _find_client_match(year_path, name)
        if match:
            # Found existing folder — DON'T auto-create. Show what's there
            # and let the user decide whether to add subfolders.
            self._show_found(year_path, match)
            return

        # No exact match — show fuzzy candidates AND a "create new folder" option
        self._show_no_match(year_path, name, fuzzy)

    def _show_no_match(self, year_path, query, fuzzy):
        """No exact match. Offers fuzzy matches (if any) + create-new button."""
        self._clear_output()
        self._out_title.configure(text="No exact match — pick or create", text_color="#B58B00")

        intro = tk.Frame(self._out_inner, bg=WHITE, padx=16, pady=12)
        intro.pack(fill="x")
        tk.Label(intro,
                 text=f"No folder named '{query}' inside",
                 font=("Segoe UI Variable", 10), bg=WHITE, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(intro, text=year_path,
                 font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")

        # Create-new option (always shown — primary action)
        sections = self._selected_sections()
        new_box = tk.Frame(self._out_inner, bg=SUCCESS_BG,
                           highlightthickness=1, highlightbackground=GREEN)
        new_box.pack(fill="x", padx=16, pady=(8, 4))
        new_inner = tk.Frame(new_box, bg=SUCCESS_BG, padx=12, pady=10)
        new_inner.pack(fill="x")
        tk.Label(new_inner, text="➕  Create new client folder",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=SUCCESS_BG, fg=SUCCESS_FG,
                 anchor="w").pack(anchor="w")
        tk.Label(new_inner,
                 text=f"Make folder '{query}' here, plus {' / '.join(sections)} subfolders.",
                 font=("Segoe UI Variable", 9),
                 bg=SUCCESS_BG, fg=TEXT_DARK).pack(anchor="w", pady=(2, 8))
        ctkh.btn(new_inner, f"Create '{query}'",
                 command=lambda: self._create_for(year_path, query,
                                                   is_new=True),
                 kind="primary", height=34).pack(anchor="w")

        if fuzzy:
            tk.Label(self._out_inner,
                     text="Or use an existing folder:",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_DARK).pack(anchor="w", padx=16, pady=(10, 4))
            list_box = tk.Frame(self._out_inner, bg=WHITE)
            list_box.pack(fill="x", padx=16, pady=(0, 8))
            for name, score in fuzzy:
                row = tk.Frame(list_box, bg=BG,
                               highlightthickness=1, highlightbackground=BORDER,
                               cursor="hand2")
                row.pack(fill="x", pady=3)
                inner_row = tk.Frame(row, bg=BG, padx=12, pady=8)
                inner_row.pack(fill="x")
                tk.Label(inner_row, text=name, font=("Segoe UI Variable", 10, "bold"),
                         bg=BG, fg=TEXT_DARK,
                         anchor="w").pack(side="left", fill="x", expand=True)
                tk.Label(inner_row, text=f"{score} word match",
                         font=("Segoe UI Variable", 8),
                         bg=BG, fg=TEXT_GRAY).pack(side="left", padx=(8, 12))
                tk.Label(inner_row, text="→  use this",
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=BG, fg=SUCCESS_FG).pack(side="right")
                for w in (row, inner_row) + tuple(inner_row.winfo_children()):
                    w.bind("<Button-1>", lambda e, n=name: self._show_found(year_path, n))

    def _show_found(self, year_path, client_name):
        """Existing folder — show contents and let the user choose to add
        missing subfolders. Never auto-creates."""
        client_path = os.path.join(year_path, client_name)
        sections = self._selected_sections()

        # Inspect what already exists for the selected sections
        rows = []
        missing_count = 0
        for rel in _subfolder_paths(sections):
            full = os.path.join(client_path, rel)
            exists = os.path.isdir(full)
            rows.append({"rel": rel, "exists": exists, "path": full})
            if not exists:
                missing_count += 1

        self._clear_output()
        self._out_title.configure(text=f"Found — {client_name}", text_color=GREEN_DARK)

        # Header
        head = tk.Frame(self._out_inner, bg=WHITE, padx=16, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="📂", font=("Segoe UI Variable", 22),
                 bg=WHITE, fg=GREEN_DARK).pack(side="left", padx=(0, 12))
        info = tk.Frame(head, bg=WHITE)
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=client_name, font=("Segoe UI Variable", 12, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w").pack(anchor="w")
        tk.Label(info, text=client_path, font=("Segoe UI Variable", 8),
                 bg=WHITE, fg=TEXT_GRAY, anchor="w").pack(anchor="w")
        ctkh.btn(head, "📁  Open job folder",
                 command=lambda: _open_folder(client_path),
                 kind="subtle", width=160).pack(side="right")

        ctkh.divider(self._out_inner).pack(fill="x", padx=16)

        # Status banner + optional create-missing button
        status = tk.Frame(self._out_inner, bg=WHITE, padx=16, pady=10)
        status.pack(fill="x")
        if not sections:
            tk.Label(status,
                     text="No sections selected — pick CONTENTS and/or EMS above to see status.",
                     font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_GRAY,
                     anchor="w").pack(anchor="w")
        elif missing_count == 0:
            tk.Label(status,
                     text=f"✓  All {' / '.join(sections)} subfolders already exist — nothing to do.",
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=GREEN_DARK,
                     anchor="w").pack(anchor="w")
        else:
            tk.Label(status,
                     text=f"⚠  {missing_count} subfolder(s) missing in {' / '.join(sections)}.",
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=WARN_FG,
                     anchor="w").pack(anchor="w", pady=(0, 6))
            ctkh.btn(
                status,
                f"➕  Create the missing {missing_count} subfolder(s)",
                command=lambda: self._create_for(year_path, client_name,
                                                  is_new=False),
                kind="primary", height=34).pack(anchor="w")

        # Per-folder breakdown — read-only here
        list_box = tk.Frame(self._out_inner, bg=WHITE, padx=16)
        list_box.pack(fill="x", pady=(0, 10))
        for r in rows:
            row = tk.Frame(list_box, bg=WHITE)
            row.pack(fill="x", pady=2)
            if r["exists"]:
                badge_text, badge_fg, badge_bg = "exists", TEXT_GRAY, "#F0F0F0"
            else:
                badge_text, badge_fg, badge_bg = "missing", "#B58B00", "#FFF4D6"
            tk.Label(row, text=badge_text, font=("Segoe UI Variable", 8, "bold"),
                     bg=badge_bg, fg=badge_fg, padx=6, pady=1, width=8
                     ).pack(side="left")
            tk.Label(row, text=r["rel"], font=("Segoe UI Variable", 9),
                     bg=WHITE, fg=TEXT_DARK).pack(side="left", padx=(8, 0))
            if r["exists"]:
                tk.Button(row, text="📁", font=("Segoe UI Variable", 9),
                          bg=WHITE, fg=TEXT_GRAY,
                          activebackground=SUCCESS_HOVER, activeforeground=SUCCESS_FG,
                          relief="flat", bd=0, padx=4, pady=0, cursor="hand2",
                          command=lambda p=r["path"]: _open_folder(p)).pack(side="left")

    def _create_for(self, year_path, client_name, is_new=False):
        client_path = os.path.join(year_path, client_name)
        sections = self._selected_sections()
        if not sections:
            self._show_error("Pick at least one section (CONTENTS / EMS) above.")
            return
        try:
            if is_new and not os.path.isdir(client_path):
                os.makedirs(client_path, exist_ok=True)
            created, results = _create_subfolders(client_path, sections)
        except OSError as ex:
            self._show_error(f"Could not create folders: {ex}")
            return

        self._show_result(client_name, client_path, created, results, is_new=is_new)
        if is_new:
            show_toast(self,
                       f"Created '{client_name}' with {len(sections)} section(s)",
                       kind="success", duration=2600)
        elif created:
            show_toast(self, f"Created {created} folder(s) for {client_name}",
                       kind="success", duration=2400)
        else:
            show_toast(self, "Folders already existed — nothing to do",
                       kind="info", duration=2200)

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def on_show(self):
        try:
            self._name_entry.focus_set()
        except Exception:
            pass


def main(argv=None):
    run_standalone(NewJobApp, geometry="900x680", minsize=(720, 520))


if __name__ == "__main__":
    main()
