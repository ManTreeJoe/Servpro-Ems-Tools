"""SharePoint recent-photos audit.

Walks the SharePoint photo share for folders modified in a configurable
window (default 7 days), maps each to its likely OneDrive job folder,
and surfaces basename-level diffs so the user can spot photos that
landed on SP but never got pulled into OD.

Used from Photo Folders' bottom action bar — kept in its own module so
the daily_photos_gui doesn't grow another 300 lines for a panel that
runs on demand.

Public entry point:
    open_sp_recent_audit(parent)
"""
import os
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

import config
import persistence
import sharepoint
from theme import (BG, BORDER, FLAG_RED, GREEN, GREEN_DARK,
                   TEXT_DARK, TEXT_GRAY, WHITE, SURFACE_2,
                   NEUTRAL_HOVER,
                   SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER, WARN_FG)
from tool_panel import ScrollableFrame, show_toast
from ui_buttons import secondary_button, done_button, link_button


# Fixed window length for the audit. The user picks a start date; the
# end is always start + this many days. Module-level so it's reachable
# from both class wrappers (the View bound methods can't see class
# attributes that lived only on the original Dialog class).
_WINDOW_DAYS = 7


# ── Folder enumeration with mtime ──────────────────────────────────────────

def _folder_mtime(path):
    """Return the most recent mtime among the folder itself and its
    immediate file children. Recursing into subfolders would catch
    deeply-nested updates but adds 10× walk cost on a Files-On-Demand
    tree — top-level scan is enough for the "did anything change in
    this job folder lately?" question we're answering."""
    if not path or not os.path.isdir(path):
        return 0.0
    try:
        latest = os.path.getmtime(path)
    except OSError:
        latest = 0.0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        m = e.stat(follow_symlinks=False).st_mtime
                        if m > latest:
                            latest = m
                except OSError:
                    continue
    except OSError:
        pass
    return latest


def _list_recent_sp_folders(start_ts, end_ts):
    """Return a list of {path, name, tech, mtime, age_days} dicts for
    every job-level SP folder modified between the given timestamps
    (inclusive on both ends).

    Tech-root and month-archive entries are excluded — they're
    organizational shells, never jobs. Falls back to an empty list on
    any IO failure rather than blowing up the dialog.
    """
    out = []
    try:
        index = sharepoint.build_sharepoint_folder_index()
    except Exception:
        index = []
    now_ts = datetime.now().timestamp()
    for entry in index:
        if entry.get("is_tech_root") or entry.get("is_month_archive"):
            continue
        path = entry.get("path") or ""
        if not path:
            continue
        mt = _folder_mtime(path)
        if mt < start_ts or mt > end_ts:
            continue
        try:
            tech = sharepoint._infer_tech(path)
        except Exception:
            tech = ""
        age_days = max(0.0, (now_ts - mt) / 86400.0)
        out.append({
            "path":     path,
            "name":     entry.get("name", ""),
            "tech":     tech,
            "mtime":    mt,
            "age_days": age_days,
        })
    out.sort(key=lambda r: -r["mtime"])
    return out


# ── OD-side resolution + diff ──────────────────────────────────────────────

def _client_for_sp_override(sp_path):
    """Reverse-lookup: find which client (if any) the user pinned this
    SP path to. Returns the canonical client key (lower-cased) or "".

    `sp_match_overrides` is `{canon_client_key: [sp_path, ...]}`, so
    this walks every bucket looking for an entry matching `sp_path`
    via case-insensitive normpath compare (Windows paths don't always
    round-trip with identical casing).
    """
    if not sp_path:
        return ""
    try:
        import persistence as _per
        # Touch a single read so the on-disk migration drains and the
        # subsequent lookup sees canonicalized keys (legacy bug).
        _per.get_sp_match_overrides("__warm__")
        state = _per._load()
    except Exception:
        return ""
    overrides = state.get("sp_match_overrides", {}) or {}
    target = os.path.normcase(os.path.normpath(sp_path))
    for client_key, paths in overrides.items():
        if not isinstance(paths, list):
            continue
        for p in paths:
            try:
                if os.path.normcase(os.path.normpath(p)) == target:
                    return client_key
            except (TypeError, ValueError):
                continue
    return ""


def _resolve_od_for_sp(sp_folder_name, audit_base, *, years,
                         sp_path=""):
    """Try to map an SP folder name to an OD job folder. Re-uses the
    same substring/token matching audit_logic uses for run-doc → folder
    resolution. Returns (path, client_name) or (None, None).

    Resolution order:
        1. **SP override pin** — when the user pinned this SP path to
           a client via `_pin_dialog`, that's an explicit "this folder
           belongs to client X" assertion. Look up the client's OD
           pin (`persistence.get_folder_path`) and return it. Highest-
           priority signal because the user made it manually.
        2. **Token-overlap fallback** — strip obvious date / stage
           tokens, walk audit_base year folders, score each candidate
           by token overlap (≥2 required).

    Without step 1, "📌 Pin to client…" was silently a no-op for
    SP Recent matching — the override was recorded but the resolver
    never consulted it, so pinned rows kept coming back unmatched.

    `years` — iterable of 4-digit years to search. The audit caller
    derives this from the time-window the user selected so a 2026 scan
    doesn't accidentally match a same-named 2024 job folder.
    `sp_path` — optional absolute SP folder path, used to look up the
    SP-override key. When omitted, only the token-overlap fallback
    runs (matches the pre-2026-05-19 behavior).
    """
    if sp_path:
        try:
            override_client = _client_for_sp_override(sp_path)
        except Exception:
            override_client = ""
        if override_client:
            try:
                od_pin = persistence.get_folder_path(override_client)
            except Exception:
                od_pin = None
            if od_pin and os.path.isdir(od_pin):
                return (od_pin, override_client)
    if not audit_base or not os.path.isdir(audit_base):
        return (None, None)
    import re as _re
    # Normalize the SP folder name for matching: drop digits, common
    # stage tokens, and punctuation.
    nl = sp_folder_name.lower()
    nl = _re.sub(r"\b\d+[/.\-_]\d+(?:[/.\-_]\d+)?\b", " ", nl)
    nl = _re.sub(r"\b(initial|monitor|demo|mit|mitigation|final|"
                  r"reading|readings|inspection|inspections|post|pre|"
                  r"work|in|progress|recon|rebuild|day|\d+)\b", " ", nl)
    nl = _re.sub(r"[^a-z ]", " ", nl).strip()
    nl = _re.sub(r"\s+", " ", nl)
    if not nl:
        return (None, None)

    candidates = []
    for y in years:
        try:
            with os.scandir(audit_base) as it:
                year_dirs = [e for e in it
                              if e.is_dir(follow_symlinks=False)
                              and str(y) in e.name
                              and not ("LA" in e.name.upper()
                                       and "FIRE" in e.name.upper())]
        except OSError:
            year_dirs = []
        for yd in year_dirs:
            try:
                with os.scandir(yd.path) as it2:
                    for e in it2:
                        if e.is_dir(follow_symlinks=False):
                            candidates.append((e.name, e.path))
            except OSError:
                continue
    sp_tokens = set(nl.split())
    if not sp_tokens:
        return (None, None)
    best = None
    best_score = 0
    for fname, fpath in candidates:
        fl = _re.sub(r"[^a-z ]", " ", fname.lower())
        fl_tokens = set(fl.split())
        # Require ≥2 token overlap to be considered a match — single-
        # name matches (last name only) cause cross-pollination across
        # unrelated clients.
        score = len(sp_tokens & fl_tokens)
        if score >= 2 and score > best_score:
            best = (fpath, fname)
            best_score = score
    if best:
        return best
    return (None, None)


def _count_missing_in_od(sp_path, od_path):
    """Return (sp_count, od_count, missing_count) — file-basename diff
    of images under the SP folder (recursive) vs OneDrive PICS for the
    matched OD job folder. Uses sharepoint's stats helper to avoid a
    second walk of the OD tree.

    `missing_count` is the number of SP files whose lowercase basename
    is NOT present in the OD tree (any subfolder under PICS / Photos).
    Doesn't fingerprint by size — basename-only is a faster heuristic
    matching the audit's primary diff signal.
    """
    sp_names = set()
    try:
        for root, _dirs, files in os.walk(sharepoint._long_path(sp_path)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in sharepoint._IMAGE_EXTS:
                    sp_names.add(f.lower())
    except OSError:
        pass

    # Walk the OD job's PICS variants (EMS/PICS, CONTENTS/PICS, root PICS)
    od_names = set()
    for parent, leaf in (("EMS", "PICS"), ("CONTENTS", "PICS"),
                          ("EMS", "Photos"), ("", "PICS"),
                          ("", "Photos")):
        parts = [p for p in (parent, leaf) if p]
        candidate = os.path.join(od_path, *parts)
        if os.path.isdir(candidate):
            try:
                names = sharepoint.list_image_names_in_tree(candidate)
                od_names |= names
            except Exception:
                continue
    # Also consult the SP-import manifest so renamed-on-import files
    # don't show as missing. We import this lazily — not every caller
    # has run_audit_gui imported, and we don't want a hard dep.
    try:
        from run_audit_gui import _read_sp_manifest_originals, _resolve_all_pics_folders
        for label, p, _n in _resolve_all_pics_folders(od_path):
            try:
                od_names |= _read_sp_manifest_originals(p)
            except Exception:
                continue
    except Exception:
        pass

    missing = len(sp_names - od_names)
    return (len(sp_names), len(od_names), missing)


# ── View (Frame, embeddable) ──────────────────────────────────────────────

class SpRecentView(tk.Frame):
    """Recent-SP-photos audit UI as a reusable Frame. Hosted by either
    `_RecentAuditDialog` (legacy Toplevel from Photo Folders' button)
    or the Audit panel's `SP Recent` tab."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._cfg        = config.load()
        self._audit_base = self._cfg.get("audit_base") or ""
        self._results    = []
        self._loading    = False
        self._build_ui()
        # Auto-run on open with default window so the user sees data
        # immediately instead of an empty panel.
        self.after(100, self._run_audit)


class _RecentAuditDialog(tk.Toplevel):
    """Standalone-window wrapper kept for the Photo Folders entry
    point. The launcher prefers the Audit `SP Recent` tab now, but
    this dialog stays available so the existing Photo Folders button
    keeps working without changes to that tool."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("SharePoint Recent-Photos Audit")
        self.configure(bg=BG)
        try:
            self.geometry("980x700")
            self.minsize(720, 480)
        except tk.TclError:
            pass
        self.transient(parent)
        self._view = SpRecentView(self)
        self._view.pack(fill="both", expand=True)

    # ── chrome ──────────────────────────────────────────────────────
    def _build_ui(self):
        # Layout convention shared with Initial Upload + Backlog so the
        # four audit tabs feel cohesive: NO redundant title (the tab
        # strip is already the title), a single thin control band with
        # view-specific primary controls on the left and 🔄 Refresh on
        # the right, an optional subtitle helper line, an italic status
        # line, then the scrollable body. Same fonts, same paddings,
        # same button styles.
        default_start = datetime.now() - timedelta(days=7)
        ctl = tk.Frame(self, bg=BG, padx=14, pady=8)
        ctl.pack(fill="x")
        tk.Label(ctl, text="Start:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._start_m_var = tk.IntVar(value=default_start.month)
        self._start_d_var = tk.IntVar(value=default_start.day)
        self._start_y_var = tk.IntVar(value=default_start.year)
        tk.Spinbox(ctl, from_=1, to=12, increment=1,
                    textvariable=self._start_m_var, width=3,
                    font=("Segoe UI Variable", 9)).pack(side="left", padx=(6, 1))
        tk.Label(ctl, text="/", font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_GRAY).pack(side="left")
        tk.Spinbox(ctl, from_=1, to=31, increment=1,
                    textvariable=self._start_d_var, width=3,
                    font=("Segoe UI Variable", 9)).pack(side="left", padx=(1, 1))
        tk.Label(ctl, text="/", font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_GRAY).pack(side="left")
        tk.Spinbox(ctl, from_=2020, to=2099, increment=1,
                    textvariable=self._start_y_var, width=5,
                    font=("Segoe UI Variable", 9)).pack(side="left", padx=(1, 6))
        self._end_lbl = tk.Label(ctl, text="",
                                  font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY)
        self._end_lbl.pack(side="left")
        for v in (self._start_m_var, self._start_d_var, self._start_y_var):
            v.trace_add("write", lambda *_a: self._refresh_end_label())
        self._refresh_end_label()

        # Quick presets — the two most common targets ("last 7" and
        # "prior week") so the user doesn't have to click spinboxes.
        secondary_button(ctl, "↺ Last 7", padx=8, pady=2,
                          font=("Segoe UI Variable", 8),
                          command=lambda: self._set_start_date(
                      datetime.now() - timedelta(days=7))
                  ).pack(side="left", padx=(8, 0))
        secondary_button(ctl, "↺ Prior wk", padx=8, pady=2,
                          font=("Segoe UI Variable", 8),
                          command=lambda: self._set_start_date(
                      datetime.now() - timedelta(days=14))
                  ).pack(side="left", padx=(4, 0))

        done_button(ctl, "🔄 Refresh", padx=12, pady=3,
                     command=self._run_audit
                  ).pack(side="right")
        # Dismissed-rows toggle — hidden rows are tracked in persistence
        # (paths the user said "don't show me this again" to). Default
        # is OFF so the visible list stays clean; flipping on re-renders
        # with the dismissed rows back in line and a per-row ↺ Restore.
        self._show_dismissed_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctl, text="Show dismissed",
                        variable=self._show_dismissed_var,
                        font=("Segoe UI Variable", 8),
                        bg=BG, fg=TEXT_GRAY, activebackground=BG,
                        selectcolor=WHITE,
                        command=lambda: self._render()
                        ).pack(side="right", padx=(0, 8))

        tk.Label(self,
                 text=("SP folders modified in this 7-day window are "
                       "scanned and diffed against their OD job folder. "
                       "Rows with missing files appear amber so you can "
                       "spot pictures that didn't make it to OneDrive."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 padx=14, anchor="w", wraplength=940,
                 justify="left").pack(fill="x")
        self._status_lbl = tk.Label(self, text="",
                                     font=("Segoe UI Variable", 8, "italic"),
                                     bg=BG, fg=TEXT_GRAY,
                                     padx=14, anchor="w")
        self._status_lbl.pack(fill="x", pady=(0, 4))

        scroll = ScrollableFrame(self, bg=BG, canvas_bg=WHITE)
        scroll.canvas.config(highlightthickness=1,
                              highlightbackground=BORDER)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._inner = scroll.inner

    # ── start-date helpers ──────────────────────────────────────────
    def _resolve_start_date(self):
        """Read the M/D/Y spinboxes into a datetime, or None when the
        combination doesn't form a real date (Feb 30, etc). Callers
        fall back to "last 7 days" on None so a typo doesn't break the
        scan, just produces a no-op."""
        try:
            m = int(self._start_m_var.get())
            d = int(self._start_d_var.get())
            y = int(self._start_y_var.get())
            return datetime(y, m, d)
        except (ValueError, TypeError):
            return None

    def _refresh_end_label(self):
        """Update the '→ <end_date>' display next to the start picker.

        Spinbox `<<write>>` traces can fire AFTER the dialog is
        destroyed (the IntVar outlives the View as long as something
        holds a reference). Without the TclError guard, that trace
        gets logged as a stack trace because `_end_lbl.config` runs
        against a dead widget. Wrap every widget access here so a
        late-firing trace is a no-op rather than a crash.
        """
        try:
            if not self._end_lbl.winfo_exists():
                return
        except tk.TclError:
            return
        sd = self._resolve_start_date()
        try:
            if sd is None:
                self._end_lbl.config(text="  →  (invalid date)", fg=FLAG_RED)
                return
            end = sd + timedelta(days=_WINDOW_DAYS)
            self._end_lbl.config(
                text=f"  →  {end.strftime('%m/%d/%Y')}  (7-day window)",
                fg=TEXT_GRAY)
        except tk.TclError:
            return

    def _set_start_date(self, dt):
        """Quick-preset hook. Setting all three vars triggers their
        write traces; the end-date label and a re-scan follow naturally."""
        self._start_m_var.set(dt.month)
        self._start_d_var.set(dt.day)
        self._start_y_var.set(dt.year)
        self._run_audit()

    # ── audit run ───────────────────────────────────────────────────
    def _run_audit(self):
        if self._loading:
            return
        sd = self._resolve_start_date()
        if sd is None:
            self._status_lbl.config(text="⚠ Invalid start date")
            return
        end = sd + timedelta(days=_WINDOW_DAYS)
        start_ts = sd.timestamp()
        end_ts   = end.timestamp()
        # Search the window's year(s) PLUS the prior year. The window
        # is keyed on SP folder mtime, but a long-running job started
        # last year still gets fresh SP folders created this year —
        # e.g. Alatorre Miguel (2025 job, Marco's SP folder created
        # 5/1/2026). A bare `{sd.year, end.year}` would miss the OD
        # folder under `2025 Jobs/` for that case. Two-year-back is
        # excluded to keep `Smith John` style cross-year name
        # collisions out of the results.
        years = sorted({sd.year, end.year, sd.year - 1, end.year - 1})

        self._loading = True
        self._status_lbl.config(text="Scanning SharePoint…")
        for w in self._inner.winfo_children():
            try: w.destroy()
            except tk.TclError: pass

        def _bg():
            try:
                folders = _list_recent_sp_folders(start_ts, end_ts)
            except Exception as ex:
                folders = []
                err = str(ex)
            else:
                err = None
            results = []
            for f in folders:
                od_path, od_name = _resolve_od_for_sp(
                    f["name"], self._audit_base, years=years,
                    sp_path=f.get("path") or "")
                sp_count = od_count = missing = 0
                if od_path:
                    sp_count, od_count, missing = _count_missing_in_od(
                        f["path"], od_path)
                else:
                    # No OD match — count SP files anyway so the user
                    # knows whether the unmatched folder has work in it.
                    try:
                        for _r, _d, files in os.walk(
                                sharepoint._long_path(f["path"])):
                            for fn in files:
                                ext = os.path.splitext(fn)[1].lower()
                                if ext in sharepoint._IMAGE_EXTS:
                                    sp_count += 1
                    except OSError:
                        pass
                results.append({
                    **f,
                    "od_path":  od_path,
                    "od_name":  od_name,
                    "sp_count": sp_count,
                    "od_count": od_count,
                    "missing":  missing,
                })

            def _done():
                # If the user closed the dialog while the bg scan was
                # still running, the after() callback fires against a
                # destroyed Toplevel/Frame — every widget touch raises
                # TclError. Bail at the start so we don't render
                # against dead widgets (the results are dropped on the
                # floor, which is correct — there's nothing to show
                # them on).
                try:
                    if not self.winfo_exists():
                        return
                except tk.TclError:
                    return
                self._loading = False
                self._results = results
                try:
                    if err:
                        self._status_lbl.config(text=f"Error: {err}")
                    else:
                        self._status_lbl.config(
                            text=(f"{len(results)} folders modified "
                                  f"{sd.strftime('%m/%d')}–"
                                  f"{end.strftime('%m/%d/%Y')}"))
                except tk.TclError:
                    return
                try:
                    self._render()
                except tk.TclError:
                    pass
            self.after(0, _done)
        threading.Thread(target=_bg, daemon=True).start()

    # ── rendering ────────────────────────────────────────────────────
    def _render(self):
        for w in self._inner.winfo_children():
            try: w.destroy()
            except tk.TclError: pass
        if not self._results:
            tk.Label(self._inner,
                     text=("✓ No SharePoint folders changed in the "
                           "selected window."),
                     font=("Segoe UI Variable", 10, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     padx=20, pady=30).pack(fill="x")
            return

        # Apply dismiss filter. The "Show dismissed" checkbox flips this
        # — when checked, dismissed rows render with a ↺ Restore button
        # in place of ✕ Dismiss; when unchecked (default), they're
        # silently hidden and the footer reports the count.
        show_dismissed = bool(self._show_dismissed_var.get())
        dismissed_paths = {
            (r.get("path") or "").strip().lower()
            for r in self._results
            if persistence.is_sp_recent_dismissed(r.get("path"))
        }
        dismissed_count = len(dismissed_paths)
        if not show_dismissed and dismissed_paths:
            visible_results = [r for r in self._results
                               if (r.get("path") or "").strip().lower()
                               not in dismissed_paths]
        else:
            visible_results = list(self._results)

        # Only actionable rows surface here: gaps (missing files in OD)
        # and unmatched (no OD job folder yet). Empty SP folders are
        # filtered out entirely — a folder with zero image files isn't
        # actionable here (no photos to import, so no work to do). The
        # "all in OD" group is also dropped — those have nothing to
        # import either. (Both counts are reported via the footer.)
        empty_count = sum(1 for r in visible_results
                           if r.get("sp_count", 0) == 0)
        gaps      = [r for r in visible_results
                     if r.get("missing", 0) > 0
                     and r.get("sp_count", 0) > 0]
        unmatched = [r for r in visible_results
                     if not r["od_path"]
                     and r.get("sp_count", 0) > 0]
        skipped_ok = sum(1 for r in visible_results
                          if r["od_path"] and r["missing"] == 0
                          and r.get("sp_count", 0) > 0)

        if not gaps and not unmatched:
            tk.Label(self._inner,
                     text=("✓ Nothing to import — every recent SP "
                           f"folder is already mirrored to OD."
                           + (f"  ({skipped_ok} folders all in OD.)"
                              if skipped_ok else "")),
                     font=("Segoe UI Variable", 10, "italic"),
                     bg=WHITE, fg=GREEN_DARK,
                     padx=20, pady=30).pack(fill="x")
            return

        for label, color, rows in (
                (f"⚠ Missing in OD ({len(gaps)})",
                 "#A6772A", gaps),
                (f"❓ No OD match ({len(unmatched)})",
                 FLAG_RED, unmatched)):
            if not rows:
                continue
            tk.Label(self._inner, text="  " + label,
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=SURFACE_2, fg=color,
                     anchor="w", padx=10, pady=4
                     ).pack(fill="x", pady=(8, 2))
            for r in rows:
                self._build_row(r)
        # Footer: tell the user what got hidden so they know the count
        # isn't lost — already-in-OD AND empty folders both fall here.
        footer_bits = []
        if skipped_ok:
            footer_bits.append(f"{skipped_ok} already in OD")
        if empty_count:
            footer_bits.append(f"{empty_count} empty")
        if dismissed_count and not show_dismissed:
            footer_bits.append(f"{dismissed_count} dismissed")
        if footer_bits:
            tk.Label(self._inner,
                     text=f"  ✓ Hidden: " + ", ".join(footer_bits),
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     anchor="w", padx=10
                     ).pack(fill="x", pady=(8, 0))

    def _build_row(self, r):
        body = tk.Frame(self._inner, bg=WHITE,
                         highlightthickness=1, highlightbackground=BORDER)
        body.pack(fill="x", padx=8, pady=2)
        inner = tk.Frame(body, bg=WHITE, padx=10, pady=6)
        inner.pack(fill="x")

        # Top: SP folder identity
        top = tk.Frame(inner, bg=WHITE)
        top.pack(fill="x")
        tk.Label(top, text=r["name"],
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=WHITE, fg=TEXT_DARK,
                 anchor="w").pack(side="left")
        meta_bits = []
        if r.get("tech"):
            meta_bits.append(f"tech: {r['tech']}")
        meta_bits.append(f"{r['age_days']:.1f}d ago")
        meta_bits.append(f"{r['sp_count']} files")
        tk.Label(top, text="  ·  " + "  ·  ".join(meta_bits),
                 font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY,
                 anchor="w").pack(side="left")

        # Right side actions. Dismiss is here so it sits next to Open SP
        # for both matched + unmatched rows. When the row was previously
        # dismissed (visible only because "Show dismissed" is on) we
        # render ↺ Restore instead.
        already_dismissed = persistence.is_sp_recent_dismissed(r.get("path"))
        if already_dismissed:
            done_button(
                top, "↺ Restore", padx=8, pady=2,
                font=("Segoe UI Variable", 8, "bold"),
                command=lambda rr=r: self._undismiss_row(rr),
            ).pack(side="right", padx=(0, 4))
        else:
            secondary_button(
                top, "✕ Dismiss", padx=8, pady=2,
                font=("Segoe UI Variable", 8),
                command=lambda rr=r: self._dismiss_row(rr),
            ).pack(side="right", padx=(0, 4))
        secondary_button(
            top, "📂 Open SP", pady=2,
            command=lambda p=r["path"]: os.startfile(p),
        ).pack(side="right")

        # Diff line
        diff = tk.Frame(inner, bg=WHITE)
        diff.pack(fill="x", pady=(4, 0))
        if r["od_path"]:
            if r["missing"] > 0:
                tk.Label(diff,
                         text=f"⚠ {r['missing']} missing in OD",
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=WHITE, fg=WARN_FG).pack(side="left")
            else:
                tk.Label(diff,
                         text="✓ all SP files present in OD",
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=WHITE, fg=GREEN_DARK).pack(side="left")
            tk.Label(diff,
                     text=f"  ·  matched: {r['od_name']}",
                     font=("Segoe UI Variable", 8),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")
            secondary_button(
                diff, "📂 Open OD", pady=2,
                command=lambda p=r["od_path"]: os.startfile(p),
            ).pack(side="right")
            # SP-import pill — always present so the user can pull
            # missing files into OD from any matched row. Three states
            # mirror the Daily Run audit's SP pill so the two tabs
            # feel like the same control:
            #   • amber 📥 SP +N new — missing files waiting to copy
            #   • blue  📁 SP (N)    — matched, all already in OD
            # Clicking runs `audit_single_client` for the matched
            # client with `then_open_sp=True`, which auto-pops the SP
            # download dialog after the audit renders. When SP Recent
            # is running standalone (no audit panel ancestor) the
            # `_import_sp_for_match` path lazy-creates a helper so
            # the dialog can still open.
            if r["missing"] > 0:
                sp_btn_text = f"📥 SP +{r['missing']} new"
                sp_btn_bg, sp_btn_fg, sp_btn_active = (
                    "#FFF4D6", "#A6772A", "#FFE9B0")
            else:
                sp_btn_text = f"📁 SP ({r['sp_count']})"
                sp_btn_bg, sp_btn_fg, sp_btn_active = (
                    "#EAF3FB", "#2C6FA8", "#D6E7F4")
            tk.Button(
                diff, text=sp_btn_text,
                font=("Segoe UI Variable", 8, "bold"),
                bg=sp_btn_bg, fg=sp_btn_fg,
                activebackground=sp_btn_active,
                relief="flat", padx=6, pady=1, cursor="hand2",
                command=lambda rr=r: self._import_sp_for_match(rr)
                ).pack(side="right", padx=(0, 4))
        else:
            tk.Label(diff,
                     text="❓ No OD job folder matched this SP folder name.",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=FLAG_RED).pack(side="left")
            # Pin button — lets the user manually attach this SP folder
            # to a client so future audits use it as an override. The
            # pin dialog also has a "Pin & Audit" button that triggers
            # the SP download dialog directly when embedded.
            secondary_button(diff, "📌 Pin to client…", padx=8, pady=2,
                              font=("Segoe UI Variable", 8),
                              command=lambda rr=r: self._pin_dialog(rr)
                              ).pack(side="right")

        # Right-click anywhere on the row → context menu. Matched rows
        # get the full shared client menu (Pin to Trello, Open card,
        # XA link, Change folder, etc — same as Audit / IUQ / Snapshot).
        # Unmatched rows get a focused two-item menu: "Pin to client…"
        # and "Dismiss" — the user asked for an explicit right-click
        # path on no-match rows so they can fix the mapping without
        # hunting the buttons.
        od_name = (r.get("od_name") or "").strip()
        if od_name:
            try:
                from job_widgets import attach_card_context_menu
                import config as _cfg
                ab = (_cfg.load().get("audit_base") or "") or None
                attach_card_context_menu(
                    self, [body], od_name, audit_base=ab)
            except Exception:
                pass
        else:
            def _show_unmatched_menu(event, rr=r):
                m = tk.Menu(self, tearoff=0)
                m.add_command(
                    label="📌 Pin to client…",
                    command=lambda: self._pin_dialog(rr))
                m.add_command(
                    label="📁 Change folder…",
                    command=lambda: self._change_folder_for_unmatched(rr))
                m.add_separator()
                m.add_command(
                    label=("↺ Restore" if persistence.is_sp_recent_dismissed(
                                rr.get("path"))
                           else "✕ Dismiss this SP folder"),
                    command=lambda: (
                        self._undismiss_row(rr)
                        if persistence.is_sp_recent_dismissed(rr.get("path"))
                        else self._dismiss_row(rr)))
                try:
                    m.tk_popup(event.x_root, event.y_root)
                finally:
                    m.grab_release()
            # Bind on both the wrapping body and the inner padded frame
            # so the right-click target covers the whole row visual.
            for w in (body, inner, top, diff):
                w.bind("<Button-3>", _show_unmatched_menu)

    def _import_sp_for_match(self, r):
        """For a row whose SP folder already maps to an OD job, run a
        background single-client audit and auto-open the SP download
        dialog ON TOP of the SP Recent tab. We deliberately do NOT
        switch to the Daily Run tab — switching tabs while the user
        was reading the SP Recent results is jarring and (per user
        feedback) confusing. The audit results still queue into the
        Daily Run tab via its `_pending_render` for whenever the user
        switches over.

        When SP Recent is running standalone (no audit panel ancestor —
        the legacy Photo Folders path), a hidden RunAuditApp helper is
        lazy-created so the SP download dialog still opens. Helper is
        cached on the panel so repeat clicks don't pay the init cost."""
        client = (r.get("od_name") or "").strip()
        if not client:
            return
        audit_app = self._find_audit_app()
        if audit_app is None:
            audit_app = self._get_or_create_helper_audit_app()
        if audit_app is None:
            messagebox.showerror(
                "Couldn't trigger audit",
                "Run Audit module unavailable — try opening this from "
                "the Audit panel's SP Recent tab instead.",
                parent=self)
            return
        try:
            audit_app.audit_single_client(client, then_open_sp=True)
            show_toast(self,
                       f"Auditing '{client}' — SP dialog will open "
                       "when done.", kind="info")
        except Exception as ex:
            messagebox.showerror("Couldn't trigger audit", str(ex),
                                  parent=self)

    def _get_or_create_helper_audit_app(self):
        """Lazy-init a hidden RunAuditApp instance for the standalone
        SP Recent dialog path. Cached so repeat clicks skip init."""
        helper = getattr(self, "_helper_audit_app", None)
        try:
            if helper is not None and helper.winfo_exists():
                return helper
        except tk.TclError:
            helper = None
        try:
            from run_audit_gui import RunAuditApp
        except Exception:
            return None
        # Silent subclass — skip the auto last-doc parse since we only
        # want the SP/import plumbing, not a refreshed daily run doc.
        class _SilentHelper(RunAuditApp):
            def _restore_last_doc(self_inner):
                pass
        host = tk.Frame(self)
        try:
            helper = _SilentHelper(host)
        except Exception:
            return None
        self._helper_audit_app = helper
        return helper

    def _known_clients(self):
        """Cached list of client folder names under audit_base/<year>/.
        Sorted alphabetically. Used as the autocomplete source for the
        pin dialog's combobox."""
        cache = getattr(self, "_known_clients_cache", None)
        if cache is not None:
            return cache
        names = []
        if self._audit_base and os.path.isdir(self._audit_base):
            try:
                with os.scandir(self._audit_base) as it:
                    year_dirs = [e for e in it
                                  if e.is_dir(follow_symlinks=False)]
            except OSError:
                year_dirs = []
            seen = set()
            for yd in year_dirs:
                try:
                    with os.scandir(yd.path) as it2:
                        for e in it2:
                            if (e.is_dir(follow_symlinks=False)
                                    and e.name not in seen):
                                seen.add(e.name)
                                names.append(e.name)
                except OSError:
                    continue
            names.sort(key=str.lower)
        self._known_clients_cache = names
        return names

    def _find_audit_app(self):
        """Walk up the widget tree looking for a RunAuditApp ancestor.
        Returns it (so we can call audit_single_client) or None when
        SP Recent is running standalone (Photo Folders' button or a
        bare _RecentAuditDialog) — in which case the 'Pin & Audit'
        button is hidden because there's no audit panel to drive."""
        w = self
        for _ in range(20):  # guard against infinite walk
            if w is None:
                return None
            if w.__class__.__name__ == "RunAuditApp":
                return w
            w = getattr(w, "master", None)
        return None

    def _dismiss_row(self, r):
        """Hide this SP folder row from future SP Recent runs. The
        dismissal persists across sessions via persistence — the user
        can review + restore via the 'Show dismissed' toggle in the
        header."""
        sp_path = r.get("path") or ""
        if not sp_path:
            return
        try:
            persistence.dismiss_sp_recent(sp_path)
        except Exception as ex:
            show_toast(self, f"Couldn't dismiss: {ex}", kind="error")
            return
        show_toast(self, f"Dismissed '{r.get('name')}'", kind="info")
        # Re-render in place — the row drops out (or flips to ↺ Restore
        # if Show dismissed is on). Avoids the full SP scan since the
        # underlying results are cached.
        try:
            self._render()
        except Exception:
            pass

    def _undismiss_row(self, r):
        """Restore a previously-dismissed SP folder so it shows up in
        the regular results list again."""
        sp_path = r.get("path") or ""
        if not sp_path:
            return
        try:
            persistence.undismiss_sp_recent(sp_path)
        except Exception as ex:
            show_toast(self, f"Couldn't restore: {ex}", kind="error")
            return
        show_toast(self, f"Restored '{r.get('name')}'", kind="info")
        try:
            self._render()
        except Exception:
            pass

    def _change_folder_for_unmatched(self, r):
        """Right-click → Change folder… on a no-OD-match row. Opens a
        folder picker rooted at the audit base, pins the chosen folder
        as the SP-match override for the client, and re-runs the audit
        so the row updates. Because no client is yet associated with
        an unmatched row, we prompt for the client name first — same
        widget set as the Pin dialog but inline."""
        from tkinter import filedialog
        sp_path = r.get("path") or ""
        sp_name = r.get("name") or ""
        if not sp_path:
            return

        # Prompt 1: which client should this folder belong to?
        from tkinter import simpledialog
        clients = self._known_clients() if hasattr(self,
                                                    "_known_clients") else []
        # Use a quick combo dialog instead of a plain askstring so the
        # user can pick from existing clients OR type freeform.
        dlg = tk.Toplevel(self)
        dlg.title("Change folder for unmatched SP")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("520x230")
            dlg.resizable(False, False)
        except tk.TclError:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        head.pack(fill="x")
        tk.Label(head, text="📁 Change folder for SP row",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
        tk.Label(head, text=sp_name,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=WARN_FG, anchor="w",
                 wraplength=480, justify="left").pack(fill="x", pady=(2, 0))
        tk.Label(head,
                 text=("Pick or type the client name, then choose the "
                       "OD job folder this SP row should map to."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=480, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))

        body_f = tk.Frame(dlg, bg=BG, padx=14)
        body_f.pack(fill="x")
        tk.Label(body_f, text="Client:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        client_var = tk.StringVar()
        from tkinter import ttk as _ttk
        cb = _ttk.Combobox(body_f, textvariable=client_var,
                            values=clients, font=("Segoe UI Variable", 10),
                            width=52)
        cb.pack(fill="x", pady=(2, 0))
        cb.focus_set()

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(fill="x", side="bottom")

        def _do_change():
            name = (client_var.get() or "").strip()
            if not name:
                messagebox.showerror("No client",
                                      "Pick or type a client name.",
                                      parent=dlg)
                return
            # Now pick the OD folder.
            initial = self._audit_base or os.path.expanduser("~")
            od_path = filedialog.askdirectory(
                title=f"Pick OD folder for {name}",
                initialdir=initial, parent=dlg)
            if not od_path:
                return
            try:
                # Record the SP-match override AND the OD folder pin —
                # both surfaces (audit + SP recent) need the binding.
                persistence.add_sp_match_override(name, sp_path)
                persistence.set_folder_path(name, od_path)
            except Exception as ex:
                messagebox.showerror("Save failed", str(ex), parent=dlg)
                return
            dlg.destroy()
            show_toast(self,
                       f"Mapped '{sp_name}' → '{name}' / "
                       f"{os.path.basename(od_path)} — refreshing…",
                       kind="success")
            try:
                self._run_audit()
            except Exception:
                pass

        secondary_button(bot, "Cancel", padx=12, pady=4,
                          command=dlg.destroy
                          ).pack(side="right", padx=(8, 0))
        done_button(bot, "Pick OD folder →", padx=14, pady=4,
                     command=_do_change
                  ).pack(side="right")

    def _pin_dialog(self, r):
        """Pin an unmatched SP folder to a client. Two-button dialog:
        'Pin only' just records the override (legacy behavior); 'Pin &
        Audit' pins AND triggers the audit panel's single-client audit
        with the SP download dialog ready to open. The latter button
        only appears when SP Recent is running embedded inside the
        Audit panel — standalone mode (Photo Folders' button) shows
        only Pin."""
        sp_path = r.get("path") or ""
        sp_name = r.get("name") or ""
        audit_app = self._find_audit_app()

        dlg = tk.Toplevel(self)
        dlg.title("Pin SP folder to client")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("520x300")
            dlg.resizable(False, False)
        except tk.TclError:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        head.pack(fill="x")
        tk.Label(head, text="📌 Pin SP folder to a client",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
        tk.Label(head, text=sp_name,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=WARN_FG, anchor="w",
                 wraplength=480, justify="left").pack(fill="x", pady=(2, 0))
        tk.Label(head,
                 text=("Pick the client whose audit row should pick up "
                       "this folder. The pin survives audits — undo it "
                       "from the SP download dialog's '× Unpin' button."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=480, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))

        body = tk.Frame(dlg, bg=BG, padx=14)
        body.pack(fill="x")
        tk.Label(body, text="Client:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        client_var = tk.StringVar()
        clients = self._known_clients()
        # ttk.Combobox supports prefix-match autocomplete out of the
        # box when state="normal" — typing narrows the dropdown via
        # the user's own keystrokes; we don't need a custom filter.
        from tkinter import ttk as _ttk
        cb = _ttk.Combobox(body, textvariable=client_var,
                            values=clients, font=("Segoe UI Variable", 10),
                            width=52)
        cb.pack(fill="x", pady=(2, 0))
        cb.focus_set()

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(fill="x", side="bottom")

        def _do_pin():
            """Record the SP→client mapping AND (when possible) the
            corresponding OD folder pin so the row stops surfacing as
            unmatched on the next scan.

            Before 2026-05-19 this only wrote `add_sp_match_override`
            — and the resolver didn't consult it, so the row kept
            returning despite repeated pin clicks. Now:
              1. Always write the SP override.
              2. If the client already has an OD pin via
                 `get_folder_path`, we're done — the resolver's new
                 override→OD-pin chain will match the row next scan.
              3. If not, pop an OD folder picker so the user can
                 supply one in the same dialog. Pin AND OD pin land
                 together — same atomic flow as
                 `_change_folder_for_unmatched`.
              4. If the user cancels the OD picker, fall back to
                 dismissing the row so it disappears anyway (the user
                 already said "I'm done with this row by pinning it").
            """
            name = (client_var.get() or "").strip()
            if not name:
                messagebox.showerror("No client",
                                      "Pick or type a client name.",
                                      parent=dlg)
                return None
            try:
                persistence.add_sp_match_override(name, sp_path)
            except Exception as ex:
                messagebox.showerror("Pin failed", str(ex), parent=dlg)
                return None
            # Does the client already have an OD pin? If yes, we're
            # done — the resolver will pick it up via the SP override
            # → folder_path chain on the next scan.
            try:
                existing_od = persistence.get_folder_path(name) or ""
            except Exception:
                existing_od = ""
            if existing_od and os.path.isdir(existing_od):
                return name
            # No OD pin yet — prompt for one inline so the row
            # actually resolves rather than just being silently
            # tagged. Cancel falls through to auto-dismiss below.
            try:
                from tkinter import filedialog as _fd
                init = self._audit_base if self._audit_base else None
                od_picked = _fd.askdirectory(
                    parent=dlg,
                    title=f"Pick the OD job folder for '{name}'",
                    initialdir=init or "")
            except Exception:
                od_picked = ""
            if od_picked:
                try:
                    persistence.set_folder_path(name, od_picked)
                except Exception as ex:
                    messagebox.showerror(
                        "Couldn't pin OD folder", str(ex), parent=dlg)
                    # Pin already stuck; don't unwind — just return
                    # so the SP override survives even when the OD
                    # write failed (probably a permissions hiccup).
            else:
                # User skipped the OD picker. Dismiss the row so the
                # pin click still has the user-visible effect they
                # expected ("this row is handled"). The SP override
                # remains — the audit panel's SP download dialog
                # still picks it up.
                try:
                    persistence.dismiss_sp_recent(sp_path)
                except Exception:
                    pass
            return name

        def _pin_only():
            name = _do_pin()
            if not name:
                return
            dlg.destroy()
            show_toast(self,
                       f"Pinned to '{name}' — refreshing list…",
                       kind="success")
            # Auto-refresh so the row flips from "❓ No OD match" to
            # "matched: <client>" without the user having to click
            # 🔄 Refresh themselves.
            try:
                self._run_audit()
            except Exception:
                pass

        def _pin_and_audit():
            name = _do_pin()
            if not name:
                return
            dlg.destroy()
            try:
                # Don't switch to the Daily Run tab — the SP download
                # dialog is a floating Toplevel that opens on top of
                # the SP Recent tab so the user stays in the context
                # they were already looking at. Audit results queue
                # for Daily Run via its `_pending_render` for
                # whenever the user switches over.
                audit_app.audit_single_client(name, then_open_sp=True)
                show_toast(self,
                           f"Pinned '{name}' — SP dialog will open "
                           "after the audit finishes.", kind="info")
            except Exception as ex:
                messagebox.showerror(
                    "Couldn't trigger audit",
                    f"Pin succeeded but audit launch failed:\n{ex}",
                    parent=self)

        secondary_button(bot, "Cancel", padx=12, pady=4,
                          command=dlg.destroy
                          ).pack(side="right", padx=(8, 0))
        if audit_app is not None:
            done_button(bot, "Pin & Audit Daily Run →", padx=14, pady=4,
                         command=_pin_and_audit
                      ).pack(side="right")
            secondary_button(bot, "Pin only", padx=12, pady=4,
                              command=_pin_only
                              ).pack(side="right", padx=(0, 8))
        else:
            # Standalone (Photo Folders' button) — no audit panel to
            # drive, just do the pin.
            done_button(bot, "Pin", padx=18, pady=4,
                         command=_pin_only).pack(side="right")


# Bind the body methods onto SpRecentView. They're written against
# _RecentAuditDialog historically but only depend on Frame-compatible
# behavior (no toplevel-only calls in the methods below __init__), so
# the same `self` semantics work on either class.
for _m in ("_build_ui", "_run_audit", "_render", "_build_row", "_pin_dialog",
           "_resolve_start_date", "_refresh_end_label", "_set_start_date",
           "_known_clients", "_find_audit_app", "_import_sp_for_match",
           "_get_or_create_helper_audit_app",
           "_dismiss_row", "_undismiss_row",
           "_change_folder_for_unmatched"):
    setattr(SpRecentView, _m, getattr(_RecentAuditDialog, _m))
del _m


def open_sp_recent_audit(parent):
    """Public entry point — used from Photo Folders' bottom action bar."""
    return _RecentAuditDialog(parent)
