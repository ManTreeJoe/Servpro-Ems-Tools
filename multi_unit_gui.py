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
from theme import (BG, BORDER, FLAG_RED, GREEN, GREEN_DARK,
                    TEXT_DARK, TEXT_GRAY, WHITE, SURFACE_2,
                    NEUTRAL_HOVER,
                    LINK_BG, LINK_FG, LINK_HOVER,
                    WARN_BG, WARN_FG, DANGER_BG, DANGER_HOVER)

from tool_panel import ScrollableFrame, ToolPanel, run_standalone, show_toast
from ui_buttons import secondary_button, link_button, icon_button


_CFG = config.load()
_AUDIT_BASE = _CFG.get("audit_base", "")


# Unit-folder name pattern. Matches the variants seen on disk:
#   "Unit 1017", "Unit 1416", "UNIT #216", "Unit 2216 2-19-26",
#   "Unit 1611(KRYSTAL) - 3.23.26", "Apt 207", "Apartment 12B".
# The 'unit'/'apt'/'apartment' anchor is required at the start of the
# folder name (with optional leading whitespace) and a digit must
# appear right after the prefix + separators. Tightened with the digit
# anchor so "United Restoration" or "Apartments LLC" won't false-match.
_UNIT_FOLDER_RE = re.compile(
    r"^\s*(?:unit|apt|apartment)\b[\s#:_-]*(?P<num>\d+)",
    re.IGNORECASE)

# Looser pattern for parsing units OUT OF arbitrary text — SP folder
# names, zip filenames, run-doc activity strings. Doesn't require the
# token to be at start-of-string; matches anywhere. Also handles a
# bare "#207" suffix that techs sometimes use ("Smith #207 Demo").
# Branches so we can require a word boundary AFTER the literal
# unit/apt/apartment prefix but NOT after the '#' character — '#' is
# not a word char so `\b` would fail there anyway.
_UNIT_TOKEN_RE = re.compile(
    r"(?:(?:unit|apt|apartment)\b|#)[\s#:_-]*(?P<num>\d+)",
    re.IGNORECASE)


def _is_unit_folder(name: str) -> bool:
    return bool(_UNIT_FOLDER_RE.match(name or ""))


def _unit_number(name: str) -> int:
    """Return the unit number for sorting, or a large sentinel for
    unparseable rows (those sort to the bottom)."""
    m = _UNIT_FOLDER_RE.match(name or "")
    if not m:
        return 10**9
    try:
        return int(m.group("num"))
    except ValueError:
        return 10**9


def parse_unit_token(text: str) -> int | None:
    """Pull a unit number out of arbitrary text. Returns None when no
    Unit/Apt/Apartment/# token with a numeric tail is found.

    Used to route SP imports / WC zips to the right unit subfolder
    when the source name carries the unit (e.g.
    'Avila Apt 207 Demo 5-10-26' → 207)."""
    if not text:
        return None
    m = _UNIT_TOKEN_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group("num"))
    except ValueError:
        return None


# Folder names we should NEVER descend into while hunting for units.
# These are internal job structure, not sub-properties — descending
# would surface a "Unit X" string from a randomly-named photo subfolder
# or pull in CONTENTS-side units that don't belong to EMS scope.
_UNIT_WALK_SKIP_DIRS = {
    "ems", "contents", "recon", "pics", "photos",
    "docs", "doc", "documents", "forms", "sketch", "sketches",
    "snapshot", "snapshots", "estimating", "estimates",
    "drying", "equipment", "eq", "ar", "from sharepoint",
}


def list_unit_subfolders(job_path: str, *, max_depth: int = 3):
    """Return [{name, path, num, rel}, ...] for every Unit/Apt folder
    found under `job_path`, walked up to `max_depth` levels deep.

    Empty list when there are none (i.e. a normal single-unit job).
    Skips the job's internal EMS / CONTENTS / PICS / DOCS subtrees so
    a randomly-named photo subfolder can't look like a unit.

    The `rel` field is the relative path from `job_path` (e.g.
    'Villaigo/Unit 101 - 95286 Burnett, Gina') so callers that need
    to show which sub-property the unit belongs to have it without
    re-computing.

    Used by Run Audit to decide whether a job is a multi-unit property
    and, if so, which destination subfolder each import should target.
    Some jobs are 2 levels deep (Action Property Management / Villaigo
    / Unit 101 …) so the walk descends through sub-property folders.
    """
    if not job_path or not os.path.isdir(job_path):
        return []
    units = []
    # BFS so we surface units regardless of which sub-property holds
    # them. (parent_path, depth) — depth 0 = job_path itself.
    frontier = [(job_path, 0)]
    while frontier:
        cur, depth = frontier.pop(0)
        try:
            with os.scandir(cur) as it:
                children = list(it)
        except OSError:
            continue
        for e in children:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name
            if _is_unit_folder(name):
                try:
                    rel = os.path.relpath(e.path, job_path)
                except ValueError:
                    rel = name
                units.append({
                    "name": name,
                    "path": e.path,
                    "num":  _unit_number(name),
                    "rel":  rel,
                })
                # Don't descend INTO a unit folder — its own contents
                # are the unit's job tree, not more units.
                continue
            if depth >= max_depth:
                continue
            # Don't descend into known internal directories.
            if name.lower() in _UNIT_WALK_SKIP_DIRS:
                continue
            frontier.append((e.path, depth + 1))
    units.sort(key=lambda u: (u["num"], u["rel"].lower()))
    return units


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


def list_subjob_folders(job_path: str, *, max_depth: int = 3):
    """Like `list_unit_subfolders` but ALSO surfaces NAMED sub-jobs —
    child folders that are their own job (contain EMS/CONTENTS/RECON)
    even when they aren't named "Unit X". Covers commercial parents whose
    sub-jobs are named by site/date (e.g. "Menifee … Kirkpatrick
    Elementary 6.9.26"). Each entry: {name, path, num, rel, kind} where
    kind = "unit" for Unit/Apt folders, "job" for named sub-jobs."""
    if not job_path or not os.path.isdir(job_path):
        return []
    out, seen = [], set()
    frontier = [(job_path, 0)]
    while frontier:
        cur, depth = frontier.pop(0)
        try:
            with os.scandir(cur) as it:
                children = list(it)
        except OSError:
            continue
        for e in children:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name
            low = name.lower()
            is_unit = _is_unit_folder(name)
            is_named = (not is_unit and low not in _UNIT_WALK_SKIP_DIRS
                        and _folder_has_job_structure(e.path))
            if is_unit or is_named:
                if e.path in seen:
                    continue
                seen.add(e.path)
                try:
                    rel = os.path.relpath(e.path, job_path)
                except ValueError:
                    rel = name
                out.append({
                    "name": name, "path": e.path,
                    "num":  _unit_number(name),
                    "rel":  rel,
                    "kind": "unit" if is_unit else "job",
                })
                continue  # it's its own job — don't descend into it
            if depth >= max_depth or low in _UNIT_WALK_SKIP_DIRS:
                continue
            frontier.append((e.path, depth + 1))
    out.sort(key=lambda u: (u["num"], u["rel"].lower()))
    return out


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


def discover_multi_unit_properties():
    """Walk every year-folder and surface any direct-child folder that
    contains ≥1 Unit-pattern subfolder. Returns a list of
    {parent_path, parent_name, year, units: [{name, path}]}.

    Sorting: parents alphabetical; units numeric by parsed unit
    number. Folders with zero unit children are dropped (they're just
    normal single-unit jobs)."""
    out = []
    for y, year_path in _year_folders():
        try:
            with os.scandir(year_path) as it:
                parents = [e for e in it
                           if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for parent in parents:
            try:
                with os.scandir(parent.path) as sub_it:
                    kids = [e for e in sub_it
                            if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            unit_kids = [{"name": e.name, "path": e.path}
                         for e in kids if _is_unit_folder(e.name)]
            # NAMED sub-jobs (commercial parent whose sub-jobs are named
            # by site/date). Require ≥2 so a normal job with one
            # "Second Claim" subfolder isn't surfaced as a property.
            named_kids = [{"name": e.name, "path": e.path}
                          for e in kids
                          if not _is_unit_folder(e.name)
                          and e.name.lower() not in _UNIT_WALK_SKIP_DIRS
                          and _folder_has_job_structure(e.path)]
            if not unit_kids and len(named_kids) < 2:
                continue
            units = unit_kids + named_kids
            units.sort(key=lambda u: (_unit_number(u["name"]),
                                       u["name"].lower()))
            out.append({
                "parent_path": parent.path,
                "parent_name": parent.name,
                "year":        y,
                "units":       units,
            })
    out.sort(key=lambda p: p["parent_name"].lower())
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
