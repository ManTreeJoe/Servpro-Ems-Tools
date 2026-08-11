"""Multi-Unit panel — commercial properties with multiple units.

Real-world folder shape (Avila Apartments 2026 is the canonical case):

    X:\\IE_Public\\2026 Jobs\\Avila Apartments 2026\\
        ├─ EMS\\                  ← property-wide files
        │    └─ PICS\\
        ├─ Unit 1017\\
        │    └─ EMS\\DOCS, EMS\\PICS, …
        ├─ Unit 1416\\
        ├─ Unit 1611(KRYSTAL) - 3.23.26\\
        ├─ UNIT #216\\RECON\\
        └─ …

Each Unit subfolder is essentially its own job (own forms, own photos,
own audit state). The standard Run Audit treats the PARENT folder as
one job and never descends, so unit-specific paperwork goes silently
unaudited.

This panel auto-discovers these properties by walking the year-folder
for any direct child with ≥1 unit-pattern subfolder, then runs a
per-unit forms + photos check using the same `audit_logic` rules as
Run Audit. Status chips roll up per unit.

A secondary "Linked properties" section shows persistence-defined
`property_groups` for the rarer case where units are NOT nested under
a shared parent (e.g. older Keystone-Highland Village convention with
top-level per-unit folders).
"""
from __future__ import annotations

import os
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import audit_logic
import config
import persistence as per
# The pure folder logic moved to multi_unit_logic so the web panels
# could stop importing this Tk module just to list folders. Imported
# back here so the Tk window keeps working off the SAME definition.
from multi_unit_logic import (            # noqa: F401 — re-exported
    parse_unit_token, list_unit_subfolders,
    discover_multi_unit_properties, list_subjob_folders,
    _UNIT_WORD_TOKEN_RE, _HASH_TOKEN_RE, _HASH_NONUNIT_CTX_RE,
    _UNIT_WALK_SKIP_DIRS,
)
from theme import (BG, BORDER, FLAG_RED, GREEN, GREEN_DARK,
                    TEXT_DARK, TEXT_GRAY, WHITE, SURFACE_2,
                    NEUTRAL_HOVER,
                    LINK_BG, LINK_FG, LINK_HOVER,
                    WARN_BG, WARN_FG, DANGER_BG, DANGER_HOVER)

from tool_panel import ScrollableFrame, ToolPanel, run_standalone, show_toast
from ui_buttons import secondary_button, link_button, icon_button


_CFG = config.load()
_AUDIT_BASE = _CFG.get("audit_base", "")


# Unit-folder name pattern + its two helpers moved to multi_unit_logic
# (sp_enrich needed them without Tk); re-exported here unchanged.
from multi_unit_logic import (          # noqa: F401,E402 — re-exported
    _UNIT_FOLDER_RE, _is_unit_folder, _unit_number,
)

# Looser pattern for parsing units OUT OF arbitrary text — SP folder
# names, zip filenames, run-doc activity strings. Doesn't require the
# token to be at start-of-string; matches anywhere.
# Bare "#207" that techs sometimes use as a unit ("Smith #207 Demo").
# GUARDED: a bare '#<digits>' is only treated as a unit when it is NOT a
# claim / job / ticket / PO / WO / invoice / policy number — those all use
# '#' too and used to false-match, mis-routing imports (audit bug #5:
# "Job #2 water"→2, "Smith Claim #12345 Demo"→12345). Unit numbers are
# ≤4 digits, so a longer run (typical of claim/ticket ids) is rejected
# outright by the {1,4}\b anchor.






# Folder names we should NEVER descend into while hunting for units.
# These are internal job structure, not sub-properties — descending
# would surface a "Unit X" string from a randomly-named photo subfolder
# or pull in CONTENTS-side units that don't belong to EMS scope.




# Subdir names that mark a folder as its OWN job (so a child containing
# one is a sub-job, regardless of name — covers commercial parents whose
# sub-jobs are named by site/date, e.g. a school district with one folder
# per campus, not "Unit X").
_JOB_ROOT_DIRS = {"ems", "contents", "recon"}


def _folder_has_job_structure(path: str) -> bool:
    """True when `path` directly contains an EMS / CONTENTS / RECON
    subfolder — i.e. it's itself a job folder, not just a photos/docs
    bucket."""
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


def _is_subjob_folder(name: str, path: str) -> bool:
    """A child folder that's its OWN job — a Unit/Apt pattern OR a NAMED
    sub-job (a commercial parent's site/date folders). Excludes the
    parent's internal structure dirs (EMS / PICS / DOCS / …)."""
    if _is_unit_folder(name):
        return True
    if (name or "").lower() in _UNIT_WALK_SKIP_DIRS:
        return False
    return _folder_has_job_structure(path)




def match_unit_for_text(units, text: str):
    """Given a unit list (from `list_unit_subfolders`) and an arbitrary
    text string, return the matching unit dict (by unit number) or None.

    Auto-routing rule: parse the unit number out of `text` with
    `parse_unit_token`, then find the unit folder with that number. If
    nothing parses or no folder matches, return None — caller falls
    back to a picker."""
    if not units or not text:
        return None
    num = parse_unit_token(text)
    if num is None:
        return None
    for u in units:
        if u.get("num") == num:
            return u
    return None


def _year_folders():
    """Resolve the year-folder paths the panel should walk. Returns
    [(year_int, path), ...] for the current + prior year so a job
    that flipped years isn't dropped."""
    if not _AUDIT_BASE or not os.path.isdir(_AUDIT_BASE):
        return []
    out = []
    year = datetime.now().year
    for y in (year, year - 1):
        p = os.path.join(_AUDIT_BASE, f"{y} Jobs")
        if os.path.isdir(p):
            out.append((y, p))
    return out




def audit_unit(unit_path):
    """Run a focused forms + photos check on one unit folder using
    the existing audit_logic helpers. Returns {form_issues,
    photo_issues, has_ems, has_pics, mtime}."""
    ems_path = os.path.join(unit_path, "EMS")
    if not os.path.isdir(ems_path):
        # Some unit folders use RECON instead of EMS. Treat that as
        # "not an EMS unit" so we don't false-flag the structure.
        return {
            "form_issues":  [],
            "photo_issues": [],
            "has_ems":      False,
            "has_pics":     False,
            "mtime":        _safe_mtime(unit_path),
        }
    docs_path = audit_logic.find_docs_dir(ems_path) or os.path.join(
        ems_path, "DOCS")
    pics_path = os.path.join(ems_path, "PICS")
    try:
        form_issues = audit_logic.check_forms(ems_path) or []
    except Exception:
        form_issues = []
    try:
        if os.path.isdir(pics_path):
            photo_issues = audit_logic.check_photos(pics_path) or []
        else:
            photo_issues = ["Initial pics"]
    except Exception:
        photo_issues = []
    return {
        "form_issues":  form_issues,
        "photo_issues": photo_issues,
        "has_ems":      True,
        "has_pics":     os.path.isdir(pics_path),
        "mtime":        _safe_mtime(unit_path),
    }


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _age_days(mtime):
    if not mtime:
        return None
    return max(0.0, (time.time() - mtime) / 86400.0)


# ── Panel ──────────────────────────────────────────────────────────────────

class MultiUnitApp(ToolPanel):
    """Property-group view. Auto-discovers parent-with-units folders
    from the year-folder; falls back to manually-defined property_groups
    for atypical layouts."""

    TOOL_TITLE = "Multi-Unit"
    TOOL_AUMID = "Servpro.EMS.MultiUnit"
    TOOL_GEOMETRY_KEY = "multi_unit_geometry"
    DEFAULT_GEOMETRY = "960x680"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Multi-Unit (commercial properties)")
        self.configure(bg=BG)
        self.minsize(700, 480)
        self.restore_geometry()
        self.bind("<Destroy>", self._on_destroy)
        self._properties: list[dict] = []
        self._loading = False
        self._build_ui()
        self._kick_scan()

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        try:
            self.save_geometry()
        except Exception:
            pass

    # ── chrome ──────────────────────────────────────────────────────────
    def _build_ui(self):
        ctl = tk.Frame(self, bg=BG, padx=14, pady=10)
        ctl.pack(fill="x")
        tk.Label(ctl, text="Multi-Unit — commercial properties",
                 font=("Fraunces", 15, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._status_lbl = tk.Label(
            ctl, text="Scanning…",
            font=("Segoe UI Variable", 9, "italic"),
            bg=BG, fg=TEXT_GRAY)
        self._status_lbl.pack(side="left", padx=(14, 0))

        self._refresh_btn = secondary_button(
            ctl, "↻ Refresh", padx=10, pady=4,
            command=self._kick_scan)
        self._refresh_btn.pack(side="right")

        sub = tk.Frame(self, bg=BG, padx=14)
        sub.pack(fill="x")
        tk.Label(sub,
                 text=("Parent folders with ≥1 Unit subfolder are "
                       "auto-detected. Per-unit chips: 📄 forms missing · "
                       "📷 photos missing · ⏱ age since last touch."),
                 font=("Segoe UI Variable", 9, "italic"),
                 bg=BG, fg=TEXT_GRAY, wraplength=900, justify="left"
                 ).pack(side="left")

        scroll = ScrollableFrame(self, bg=BG, padx=14, pady=8)
        scroll.pack(fill="both", expand=True)
        self._body = scroll.inner

    # ── scan ────────────────────────────────────────────────────────────
    def _kick_scan(self):
        if self._loading:
            return
        self._loading = True
        try:
            self._refresh_btn.configure(text="…scanning", state="disabled")
            self._status_lbl.configure(text="Scanning year-folders…")
        except tk.TclError:
            pass

        def _bg():
            try:
                props = discover_multi_unit_properties()
                # Audit each unit. This is filesystem-only — no Trello
                # round-trips — so it stays fast even for properties
                # with 10+ units.
                for p in props:
                    for u in p["units"]:
                        u["audit"] = audit_unit(u["path"])
            except Exception as ex:
                err = str(ex)
                props = []
            else:
                err = None
            def _done():
                self._loading = False
                try:
                    self._refresh_btn.configure(text="↻ Refresh",
                                                  state="normal")
                except tk.TclError:
                    pass
                if err:
                    try:
                        self._status_lbl.configure(text=f"Error: {err}")
                    except tk.TclError:
                        pass
                    return
                self._properties = props
                self._render()
            try:
                self.after(0, _done)
            except tk.TclError:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    # ── render ──────────────────────────────────────────────────────────
    def _render(self):
        for w in self._body.winfo_children():
            try: w.destroy()
            except tk.TclError: pass

        total_units = sum(len(p["units"]) for p in self._properties)
        flagged_units = 0
        for p in self._properties:
            for u in p["units"]:
                a = u.get("audit") or {}
                if a.get("form_issues") or a.get("photo_issues"):
                    flagged_units += 1
        try:
            self._status_lbl.configure(
                text=(f"{len(self._properties)} properties · "
                      f"{total_units} units · "
                      f"{flagged_units} flagged"))
        except tk.TclError:
            pass

        if not self._properties:
            tk.Label(
                self._body,
                text=("No multi-unit properties detected.\n\n"
                      "A property auto-shows when its folder contains "
                      "≥1 'Unit …' subfolder (e.g. Avila Apartments "
                      "2026 → Unit 1017, Unit 1416, …)."),
                font=("Segoe UI Variable", 10, "italic"),
                bg=BG, fg=TEXT_GRAY, justify="left",
                anchor="w", padx=20, pady=40
            ).pack(fill="x")
            self._render_manual_groups_section()
            return

        for p in self._properties:
            self._build_property_card(p)

        self._render_manual_groups_section()

        try:
            self.after_idle(self.sweep_tooltips)
        except Exception:
            pass

    def _build_property_card(self, prop):
        units = prop["units"]
        flagged = sum(
            1 for u in units
            if (u.get("audit") or {}).get("form_issues")
            or (u.get("audit") or {}).get("photo_issues")
        )

        wrap = tk.Frame(self._body, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="x", pady=(0, 12))

        # Header
        hdr = tk.Frame(wrap, bg=WHITE, padx=12, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"🏢  {prop['parent_name']}",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=WHITE, fg=TEXT_DARK).pack(side="left")
        meta = f"{len(units)} unit{'s' if len(units) != 1 else ''}"
        if flagged:
            meta += f" · {flagged} flagged"
        tk.Label(hdr, text=f"  ·  {meta}",
                 font=("Segoe UI Variable", 9), bg=WHITE,
                 fg=FLAG_RED if flagged else TEXT_GRAY
                 ).pack(side="left")

        link_button(
            hdr, "📁 Open property", padx=8, pady=2,
            font=("Segoe UI Variable", 8, "bold"),
            command=lambda p=prop["parent_path"]: self._open_folder(p)
        ).pack(side="right")

        # Unit rows
        body = tk.Frame(wrap, bg=WHITE, padx=12)
        body.pack(fill="x", pady=(0, 8))
        for u in units:
            self._build_unit_row(body, u)

    def _build_unit_row(self, parent, unit):
        a = unit.get("audit") or {}
        fi = a.get("form_issues") or []
        pi = a.get("photo_issues") or []
        is_flagged = bool(fi or pi)
        no_ems = not a.get("has_ems")

        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x", pady=2)

        # Status chip
        if no_ems:
            chip_bg, chip_fg, chip_text = "#EEEEEE", TEXT_GRAY, " — "
        elif is_flagged:
            chip_bg, chip_fg, chip_text = "#FBEAE5", FLAG_RED, " FLAG "
        else:
            chip_bg, chip_fg, chip_text = "#E8F5EE", GREEN_DARK, " OK "
        tk.Label(row, text=chip_text,
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=chip_bg, fg=chip_fg, padx=4
                 ).pack(side="left")

        tk.Label(row, text=f"  {unit['name']}",
                 font=("Segoe UI Variable", 9), bg=WHITE,
                 fg=TEXT_DARK if not no_ems else TEXT_GRAY,
                 anchor="w").pack(side="left", fill="x", expand=True)

        if fi:
            tk.Label(row, text=f" 📄 {len(fi)} ",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=WARN_BG, fg=WARN_FG,
                     padx=4).pack(side="left", padx=(2, 0))
        if pi:
            tk.Label(row, text=f" 📷 {len(pi)} ",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=WARN_BG, fg=WARN_FG,
                     padx=4).pack(side="left", padx=(2, 0))
        age = _age_days(a.get("mtime"))
        if age is not None and age >= 3:
            tk.Label(row, text=f" ⏱ {int(age)}d ",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=DANGER_BG if age >= 10 else WARN_BG,
                     fg=FLAG_RED if age >= 10 else "#A6772A",
                     padx=4).pack(side="left", padx=(2, 0))
        if no_ems:
            tk.Label(row, text=" no EMS ",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY
                     ).pack(side="left", padx=(2, 0))

        icon_button(
            row, "📁", padx=4, pady=0, fg=TEXT_DARK,
            command=lambda p=unit["path"]: self._open_folder(p),
            tooltip="Open unit folder"
        ).pack(side="right", padx=(4, 0))

    # ── manual / linked-siblings fallback section ──────────────────────
    def _render_manual_groups_section(self):
        """Render any persistence-defined property_groups in a separate
        section below the auto-discovered list. Lets the user keep
        manual links for properties whose unit folders DON'T live
        under a single parent (older Keystone-Highland Village
        convention)."""
        groups = per.get_property_groups()
        if not groups:
            return

        # Section header
        sep = tk.Frame(self._body, bg=BG)
        sep.pack(fill="x", pady=(16, 4))
        tk.Label(sep,
                 text="Linked properties (manual)",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        tk.Label(sep,
                 text=("  ·  for properties whose units live in "
                       "separate top-level folders"),
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=BG, fg=TEXT_GRAY).pack(side="left")

        # Backlog index for status chips
        try:
            import audit_export
            rows = audit_export.load_audit_backlog() or []
        except Exception:
            rows = []
        backlog = {}
        for r in rows:
            fld = (r.get("folder") or "").strip()
            if fld:
                backlog[fld] = r

        for name in sorted(groups.keys(), key=str.lower):
            g = groups[name] or {}
            folders = list(g.get("folders") or [])
            wrap = tk.Frame(self._body, bg=WHITE,
                            highlightthickness=1,
                            highlightbackground=BORDER)
            wrap.pack(fill="x", pady=(0, 8))
            hdr = tk.Frame(wrap, bg=WHITE, padx=12, pady=6)
            hdr.pack(fill="x")
            tk.Label(hdr, text=f"🔗  {name}",
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=TEXT_DARK).pack(side="left")
            tk.Label(hdr,
                     text=f"  ·  {len(folders)} unit"
                          f"{'s' if len(folders) != 1 else ''}",
                     font=("Segoe UI Variable", 9), bg=WHITE,
                     fg=TEXT_GRAY).pack(side="left")
            icon_button(
                hdr, "✕", fg=FLAG_RED, hover=DANGER_HOVER,
                padx=6, pady=1,
                command=lambda n=name: self._delete_manual_group(n),
                tooltip="Delete this manual property group",
            ).pack(side="right")

            body = tk.Frame(wrap, bg=WHITE, padx=12)
            body.pack(fill="x", pady=(0, 6))
            for f in folders:
                row = tk.Frame(body, bg=WHITE)
                row.pack(fill="x", pady=1)
                br = backlog.get(f)
                status = (br.get("status") if br else "—") or "—"
                status = status.upper()
                if status == "FLAG":
                    chip_bg, chip_fg = "#FBEAE5", FLAG_RED
                elif status == "OK":
                    chip_bg, chip_fg = "#E8F5EE", GREEN_DARK
                else:
                    chip_bg, chip_fg = "#EEEEEE", TEXT_GRAY
                tk.Label(row, text=f" {status} ",
                         font=("Segoe UI Variable", 8, "bold"),
                         bg=chip_bg, fg=chip_fg,
                         padx=4).pack(side="left")
                tk.Label(row, text=f"  {f}",
                         font=("Segoe UI Variable", 9), bg=WHITE,
                         fg=TEXT_DARK, anchor="w"
                         ).pack(side="left", fill="x", expand=True)

    def _delete_manual_group(self, name):
        if not messagebox.askyesno(
                "Delete linked property?",
                f"Remove linked property '{name}'?\n\n"
                "Folders themselves are not touched.",
                parent=self):
            return
        per.delete_property_group(name)
        self._render()

    def _open_folder(self, path):
        try:
            os.startfile(path)
        except OSError as ex:
            messagebox.showerror("Couldn't open folder", str(ex),
                                  parent=self)


def main(argv=None):
    run_standalone(MultiUnitApp, geometry="960x680", minsize=(700, 480))


if __name__ == "__main__":
    main()
