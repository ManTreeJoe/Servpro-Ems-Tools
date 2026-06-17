"""Pipeline panel — overall job tracker across the lifecycle.

One row per Trello card, grouped by stage. Filter chips at the top
double as both stage navigation and a stage-counts funnel. Body is a
sortable Treeview with Client / Stage / Days-in-stage / Total-age /
Last-activity / Owner columns. Stalled rows (days_in_stage past the
per-stage threshold) get a warning tint.

Data lives in ems_db.job_lifecycle, populated by
pipeline_stages.sync_workspace(). First panel open prompts a sync if
the table's empty; ↻ Sync button re-runs the workspace walk on demand.
"""
from __future__ import annotations

import datetime as _dt
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from theme import (BG, BORDER, FLAG_RED, GREEN, GREEN_DARK, INFO_BG,
                    INFO_FG, SURFACE_2, TEXT_DARK, TEXT_GRAY, WARN_BG,
                    WARN_FG, WHITE)
from tool_panel import ToolPanel, attach_tooltip, run_standalone, show_toast
from ui_buttons import done_button, secondary_button

import ems_db
import pipeline_stages as ps


_ALL = "__all__"


class PipelineApp(ToolPanel):
    TOOL_TITLE = "Pipeline"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._filter_stage = _ALL
        self._chip_btns: dict[str, tk.Widget] = {}
        self._search_text = ""
        self._sort_col = "days_in_stage"
        self._sort_reverse = True
        self._build_ui()
        # Defer the initial load so the UI paints before reading the DB.
        try:
            self.after(150, self._load)
        except Exception:
            pass

    # ── UI scaffold ──────────────────────────────────────────────────────
    def _build_ui(self):
        head = tk.Frame(self, bg=BG, padx=20, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="🛤  Pipeline",
                  font=("Fraunces", 16, "bold"),
                  bg=BG, fg=TEXT_DARK).pack(side="left")
        tk.Label(head,
                  text="Every job from card-created to paid",
                  font=("Segoe UI Variable", 9, "italic"),
                  bg=BG, fg=TEXT_GRAY).pack(side="left", padx=(12, 0))

        self._status_lbl = tk.Label(
            head, text="",
            font=("Segoe UI Variable", 9, "italic"),
            bg=BG, fg=TEXT_GRAY)
        self._status_lbl.pack(side="right")
        self._sync_btn = secondary_button(
            head, "↻  Sync from Trello",
            command=self._do_sync)
        self._sync_btn.pack(side="right", padx=(0, 10))
        secondary_button(
            head, "💾  Export",
            command=self._export_to_excel
            ).pack(side="right", padx=(0, 6))
        secondary_button(
            head, "⚙  Thresholds…",
            command=self._open_thresholds_dialog
            ).pack(side="right", padx=(0, 6))

        # Filter chips — one per stage + All. Counts populate on _load.
        chip_bar = tk.Frame(self, bg=BG, padx=20, pady=4)
        chip_bar.pack(fill="x")
        self._chip_btns = {}
        self._add_chip(chip_bar, _ALL, "All")
        for stage in ps.STAGES:
            self._add_chip(chip_bar, stage, ps.STAGE_LABELS[stage])

        # Search box
        ctl = tk.Frame(self, bg=BG, padx=20, pady=4)
        ctl.pack(fill="x")
        tk.Label(ctl, text="🔍",
                  font=("Segoe UI Emoji", 10),
                  bg=BG, fg=TEXT_GRAY).pack(side="left")
        self._search_var = tk.StringVar()
        ent = tk.Entry(ctl, textvariable=self._search_var,
                        font=("Segoe UI Variable", 10),
                        bg=WHITE, fg=TEXT_DARK,
                        relief="flat", highlightthickness=1,
                        highlightbackground=BORDER,
                        highlightcolor=GREEN_DARK,
                        width=40)
        ent.pack(side="left", padx=(6, 0), ipady=3)
        self._search_var.trace_add(
            "write", lambda *_a: self._apply_filter())
        tk.Label(ctl, text="(client name)",
                  font=("Segoe UI Variable", 8, "italic"),
                  bg=BG, fg=TEXT_GRAY).pack(side="left", padx=(8, 0))

        # Table
        body = tk.Frame(self, bg=BG, padx=20)
        body.pack(fill="both", expand=True, pady=(4, 14))
        cols = ("client", "stage", "days_in_stage", "age",
                 "last_activity", "owner", "board")
        self._tree = ttk.Treeview(body, columns=cols, show="headings",
                                    selectmode="browse")
        headings = (
            ("client",        "Client",        260),
            ("stage",         "Stage",         130),
            ("days_in_stage", "Days in Stage",  90),
            ("age",           "Age",            70),
            ("last_activity", "Last Activity", 130),
            ("owner",         "Owner",         120),
            ("board",         "Board / Lane",  220),
        )
        for cid, label, w in headings:
            self._tree.heading(
                cid, text=label,
                command=lambda c=cid: self._sort_by(c))
            self._tree.column(cid, width=w, anchor="w")
        # Stall coloring tags
        self._tree.tag_configure("stall_warn",
                                  background="#FFF4D6", foreground=WARN_FG)
        self._tree.tag_configure("stall_bad",
                                  background="#FBEAE5", foreground=FLAG_RED)

        sb = ttk.Scrollbar(body, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        # Right-click → quick actions on the selected card
        menu = tk.Menu(self._tree, tearoff=0)
        menu.add_command(label="Open Trello card",
                          command=self._open_trello)
        menu.add_command(label="📜 Show timeline…",
                          command=self._show_timeline)
        menu.add_command(label="Copy client name",
                          command=self._copy_client)
        self._row_menu = menu
        self._tree.bind("<Button-3>", self._handle_right_click)
        self._tree.bind("<Double-1>", lambda _e: self._show_timeline())

    def _add_chip(self, parent, key, label):
        """Add a filter chip. Stage key '__all__' = no filter."""
        btn = tk.Button(
            parent, text=f"{label}",
            font=("Segoe UI Variable", 9, "bold"),
            bg=SURFACE_2, fg=TEXT_DARK,
            activebackground=GREEN, activeforeground=WHITE,
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=lambda k=key: self._set_filter(k))
        btn.pack(side="left", padx=(0, 6))
        self._chip_btns[key] = btn

    # ── Filter / sort ────────────────────────────────────────────────────
    def _set_filter(self, stage_key):
        self._filter_stage = stage_key
        self._restyle_chips()
        self._apply_filter()

    def _restyle_chips(self):
        for key, btn in self._chip_btns.items():
            try:
                if key == self._filter_stage:
                    btn.config(bg=GREEN, fg=WHITE)
                else:
                    btn.config(bg=SURFACE_2, fg=TEXT_DARK)
            except tk.TclError:
                pass

    def _apply_filter(self):
        """Repopulate the tree from self._rows, respecting active stage
        + search filters + current sort column."""
        try:
            search = (self._search_var.get() or "").lower().strip()
        except tk.TclError:
            search = ""
        for iid in self._tree.get_children():
            try:
                self._tree.delete(iid)
            except tk.TclError:
                pass
        visible = []
        for r in self._rows:
            if (self._filter_stage != _ALL
                    and (r.get("current_stage") or "")
                    != self._filter_stage):
                continue
            if search:
                hay = (r.get("client_display") or "").lower()
                if search not in hay:
                    continue
            visible.append(r)
        visible.sort(key=self._sort_key, reverse=self._sort_reverse)
        # Pre-compute the history snapshot once per refresh so the
        # per-row anomaly check is a dict lookup, not a re-query.
        # Both calls are wrapped because they were added in Phase 4 —
        # a running process with the pre-Phase-4 module loaded (e.g.
        # PyInstaller bundle that hasn't been rebuilt) would AttributeError
        # without the guard.
        try:
            self._anomaly_history = ps.historical_stage_stats()
        except Exception:
            self._anomaly_history = {}
        _is_anomaly = getattr(ps, "is_anomaly", None)
        anomaly_count = 0
        for r in visible:
            self._insert_row(r)
            if _is_anomaly is not None:
                try:
                    if _is_anomaly(r, history=self._anomaly_history):
                        anomaly_count += 1
                except Exception:
                    pass
        status = (f"{len(visible)} shown  ·  "
                  f"{len(self._rows)} total")
        if anomaly_count:
            status += f"  ·  🚨 {anomaly_count} anomalies"
        self._status_lbl.config(text=status)

    def _sort_key(self, r):
        col = self._sort_col
        if col == "client":
            return (r.get("client_display") or "").lower()
        if col == "stage":
            try:
                return ps.STAGES.index(r.get("current_stage") or "")
            except ValueError:
                return len(ps.STAGES)
        if col == "days_in_stage":
            return ps.days_in_stage(r)
        if col == "age":
            return ps.days_since_created(r)
        if col == "last_activity":
            return r.get("last_activity_at") or ""
        if col == "owner":
            return (r.get("owner") or "").lower()
        if col == "board":
            return ((r.get("board_name") or "") + " / "
                    + (r.get("list_name") or "")).lower()
        return ""

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            # Default direction: most recent / most days first.
            self._sort_reverse = col in ("days_in_stage", "age",
                                          "last_activity")
        self._apply_filter()

    # ── Row rendering ────────────────────────────────────────────────────
    def _insert_row(self, r):
        d_in = ps.days_in_stage(r)
        d_age = ps.days_since_created(r)
        stage = r.get("current_stage") or ""
        threshold = ps.get_thresholds().get(stage, 9999)
        tags = ()
        if d_in > threshold * 2:
            tags = ("stall_bad",)
        elif d_in > threshold:
            tags = ("stall_warn",)
        # Anomaly check — 3× historical median for this stage. Distinct
        # from stalls (which are vs static thresholds). Renders a 🚨
        # badge in the Days-in-Stage cell so it pops without needing
        # an extra column. _anomaly_history is computed once per refresh
        # in _apply_filter so we don't re-query per-row. Wrapped in
        # getattr because is_anomaly was added in Phase 4 — older
        # pipeline_stages (e.g. PyInstaller bundle) lacks it.
        days_label = f"{d_in}d"
        _is_anomaly = getattr(ps, "is_anomaly", None)
        if (_is_anomaly is not None
                and getattr(self, "_anomaly_history", None) is not None):
            try:
                if _is_anomaly(r, history=self._anomaly_history):
                    days_label = f"🚨 {d_in}d"
                    # Promote to bad tint even if not above 2×
                    # threshold — anomalies are by definition way past
                    # their stage's historical norm.
                    tags = ("stall_bad",)
            except Exception:
                pass
        last = (r.get("last_activity_at") or "")[:10]  # YYYY-MM-DD
        board_lane = ((r.get("board_name") or "") + " / "
                      + (r.get("list_name") or ""))
        iid = self._tree.insert(
            "", "end",
            values=(
                r.get("client_display") or "",
                ps.STAGE_LABELS.get(stage, stage),
                days_label,
                f"{d_age}d",
                last,
                r.get("owner") or "",
                board_lane,
            ),
            tags=tags)
        self._row_by_iid_set(iid, r)

    def _row_by_iid_set(self, iid, r):
        if not hasattr(self, "_row_by_iid"):
            self._row_by_iid = {}
        self._row_by_iid[iid] = r

    def _selected_row(self):
        try:
            sel = self._tree.selection()
        except tk.TclError:
            return None
        if not sel:
            return None
        return getattr(self, "_row_by_iid", {}).get(sel[0])

    def _handle_right_click(self, event):
        iid = self._tree.identify_row(event.y)
        if iid:
            self._tree.selection_set(iid)
            try:
                self._row_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._row_menu.grab_release()

    def _open_trello(self):
        r = self._selected_row()
        if not r:
            return
        url = r.get("card_url") or ""
        if not url:
            return
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _show_timeline(self):
        """Per-job stage-history dialog. Walks job_stage_transitions
        oldest-first so the user reads top-to-bottom in chronological
        order. Each row: from-stage → to-stage chip, transition date,
        days in the from-stage. Header shows current stage + total age.

        Cards with zero transitions in the log (newly-tracked + never
        moved) get a fall-through message that tells the user this
        card hasn't transitioned since pipeline tracking began."""
        r = self._selected_row()
        if not r:
            return
        cid = r.get("card_id")
        if not cid:
            return
        client = r.get("client_display") or "(no client)"
        try:
            history = ems_db.list_transitions(card_id=cid, order="ASC")
        except Exception:
            history = []

        dlg = tk.Toplevel(self)
        dlg.title(f"Timeline — {client}")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        try:
            dlg.geometry("560x520")
            dlg.minsize(480, 320)
        except tk.TclError:
            pass

        # Header
        head = tk.Frame(dlg, bg=BG, padx=18, pady=12)
        head.pack(fill="x")
        tk.Label(head, text=client,
                  font=("Fraunces", 14, "bold"),
                  bg=BG, fg=TEXT_DARK).pack(anchor="w")
        cur_stage = r.get("current_stage") or ""
        d_in = ps.days_in_stage(r)
        d_age = ps.days_since_created(r)
        tk.Label(head,
                  text=(f"Current: {ps.STAGE_LABELS.get(cur_stage, cur_stage)}"
                        f" · {d_in}d in stage · {d_age}d total age"),
                  font=("Segoe UI Variable", 9),
                  bg=BG, fg=TEXT_GRAY).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(dlg, bg=WHITE,
                         highlightthickness=1, highlightbackground=BORDER,
                         padx=14, pady=10)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        if not history:
            tk.Label(body,
                      text=("No stage transitions recorded yet — this "
                            "card hasn't moved since pipeline tracking "
                            "began. Future moves will appear here."),
                      font=("Segoe UI Variable", 9, "italic"),
                      bg=WHITE, fg=TEXT_GRAY,
                      wraplength=480, justify="left"
                      ).pack(anchor="w", pady=8)
        else:
            # Visual timeline rendered as a vertical sequence of rows.
            # Each transition: prior stage chip → arrow → new stage chip
            # + date + days spent in the prior stage.
            for t in history:
                row = tk.Frame(body, bg=WHITE)
                row.pack(fill="x", pady=2)
                from_s = t.get("from_stage") or ""
                to_s   = t.get("to_stage") or ""
                tk.Label(row,
                          text=ps.STAGE_LABELS.get(from_s, from_s),
                          font=("Segoe UI Variable", 8, "bold"),
                          bg=SURFACE_2, fg=TEXT_DARK,
                          padx=6, pady=2).pack(side="left")
                tk.Label(row, text="  →  ",
                          font=("Segoe UI Variable", 9),
                          bg=WHITE, fg=TEXT_GRAY).pack(side="left")
                tk.Label(row,
                          text=ps.STAGE_LABELS.get(to_s, to_s),
                          font=("Segoe UI Variable", 8, "bold"),
                          bg=SURFACE_2, fg=TEXT_DARK,
                          padx=6, pady=2).pack(side="left")
                when = (t.get("transitioned_at") or "")[:10]
                tk.Label(row, text=f"  {when}",
                          font=("Segoe UI Variable", 9),
                          bg=WHITE, fg=TEXT_GRAY).pack(side="left",
                                                        padx=(8, 0))
                d = t.get("days_in_from_stage") or 0
                tk.Label(row, text=f"({d}d in prior stage)",
                          font=("Segoe UI Variable", 8, "italic"),
                          bg=WHITE, fg=TEXT_GRAY
                          ).pack(side="left", padx=(8, 0))

            # Final row: the card sits in its current stage now.
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(8, 6))
            final = tk.Frame(body, bg=WHITE)
            final.pack(fill="x")
            tk.Label(final, text="now →",
                      font=("Segoe UI Variable", 9, "bold"),
                      bg=WHITE, fg=TEXT_DARK).pack(side="left")
            tk.Label(final,
                      text=ps.STAGE_LABELS.get(cur_stage, cur_stage),
                      font=("Segoe UI Variable", 9, "bold"),
                      bg=GREEN, fg=WHITE,
                      padx=6, pady=2).pack(side="left", padx=(8, 0))
            tk.Label(final, text=f"  ({d_in}d so far)",
                      font=("Segoe UI Variable", 8, "italic"),
                      bg=WHITE, fg=TEXT_GRAY).pack(side="left", padx=(8, 0))

        # Footer
        foot = tk.Frame(dlg, bg=BG, padx=18, pady=10)
        foot.pack(fill="x", side="bottom")
        tk.Button(foot, text="Close",
                   font=("Segoe UI Variable", 9, "bold"),
                   bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                   relief="flat", padx=14, pady=4,
                   command=dlg.destroy).pack(side="right")
        url = r.get("card_url") or ""
        if url:
            tk.Button(foot, text="🔗 Open Trello",
                       font=("Segoe UI Variable", 9), bg=SURFACE_2,
                       fg=TEXT_DARK, relief="flat", padx=12, pady=4,
                       command=lambda u=url: (__import__("webbrowser")
                                                .open(u))
                       ).pack(side="right", padx=(0, 8))

    def _copy_client(self):
        r = self._selected_row()
        if not r:
            return
        name = r.get("client_display") or ""
        try:
            self.clipboard_clear()
            self.clipboard_append(name)
        except tk.TclError:
            pass

    # ── Load / sync ──────────────────────────────────────────────────────
    def _load(self):
        """Read from ems_db and paint. If table is empty, prompt to sync."""
        # Self-heal pass: rows synced before the dateLastActivity fix
        # all had stage_entered_at stamped at first-sync moment, so
        # they read "0d in stage" even when the card had been in the
        # lane for weeks. Re-anchors to last_activity_at where that's
        # older. Cheap (one UPDATE) so it's fine to run every load.
        try:
            ems_db.backfill_stage_entered_dates()
        except Exception:
            pass
        # Drop any template / label / admin cards inserted before the
        # skip filter was added. Cheap (DELETE on a small table) and
        # makes the panel reflect the filter immediately without
        # waiting for the next full sync.
        try:
            ps.purge_skipped_lifecycle_rows()
        except Exception:
            pass
        try:
            rows = ems_db.lifecycle_list(paid_window_days=30)
        except Exception as ex:
            messagebox.showerror("Pipeline load failed", str(ex),
                                  parent=self)
            return
        self._rows = rows
        # Update chip counts
        for key, btn in self._chip_btns.items():
            if key == _ALL:
                btn.config(text=f"All ({len(rows)})")
                continue
            n = sum(1 for r in rows
                    if (r.get("current_stage") or "") == key)
            btn.config(text=f"{ps.STAGE_LABELS[key]} ({n})")
        self._restyle_chips()
        self._apply_filter()
        if not rows:
            self._status_lbl.config(
                text="Empty — click ↻ Sync from Trello to populate.")

    def _do_sync(self):
        """Run pipeline_stages.sync_workspace() in a background thread,
        then refresh the panel."""
        try:
            self._sync_btn.config(state="disabled")
        except tk.TclError:
            pass
        self._status_lbl.config(text="Sync starting…")

        def _bg():
            err = None
            result = None
            enrich_result = None
            try:
                def _progress(i, n, name):
                    try:
                        self.after(0, lambda: self._status_lbl.config(
                            text=f"Sync {i}/{n}: {name}…"))
                    except Exception:
                        pass
                result = ps.sync_workspace(progress_cb=_progress)
                # Phase 4 enrichment — replace the dateLastActivity
                # proxy with the exact lane-entry date from card
                # actions. Slow (~1 API call per un-enriched card),
                # so it runs AFTER the main sync. The first call
                # after a fresh DB hits every card; subsequent runs
                # only touch new cards + cards that transitioned
                # stages since the last enrichment.
                def _enrich_progress(i, n, card_id):
                    try:
                        self.after(0, lambda: self._status_lbl.config(
                            text=f"Reading Trello history "
                                 f"{i}/{n}…"))
                    except Exception:
                        pass
                enrich_result = ps.enrich_stage_entered_from_actions(
                    progress_cb=_enrich_progress)
            except Exception as ex:
                err = ex

            def _done():
                try:
                    self._sync_btn.config(state="normal")
                except tk.TclError:
                    pass
                if err is not None:
                    messagebox.showerror(
                        "Sync failed",
                        f"{type(err).__name__}: {err}",
                        parent=self)
                    self._status_lbl.config(text="Sync failed")
                    return
                status_bits = [
                    f"Synced {result.get('cards', 0)} cards "
                    f"from {result.get('boards', 0)} boards"]
                if enrich_result and enrich_result.get("enriched"):
                    status_bits.append(
                        f"history: {enrich_result['enriched']} dated")
                self._status_lbl.config(text="  ·  ".join(status_bits))
                self._load()
                try:
                    show_toast(self, "Pipeline synced", kind="success",
                                duration=2000)
                except Exception:
                    pass

            try:
                self.after(0, _done)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()


    # ── Threshold config + export ───────────────────────────────────────
    def _open_thresholds_dialog(self):
        """Open a modal editor for per-stage stall thresholds. Values
        are persisted via pipeline_stages.set_threshold and immediately
        re-style every stalled row + KPI median on next refresh."""
        dlg = tk.Toplevel(self)
        dlg.title("Stage stall thresholds")
        dlg.resizable(False, False)
        dlg.grab_set()
        wf = tk.Frame(dlg, bg=BG, padx=20, pady=14)
        wf.pack(fill="both", expand=True)
        tk.Label(wf,
                  text="Days a stage must exceed before a row is flagged "
                       "stalled. Used by the Pipeline panel + Hygiene "
                       "'Stalled in stage' section + KPI cycle-time "
                       "coloring.",
                  font=("Segoe UI Variable", 9),
                  bg=BG, fg=TEXT_GRAY, wraplength=420, justify="left"
                  ).pack(anchor="w", pady=(0, 10))

        current = ps.get_thresholds()
        spin_vars: dict[str, tk.IntVar] = {}
        grid = tk.Frame(wf, bg=BG)
        grid.pack(fill="x")
        for i, stage in enumerate(ps.STAGES):
            label = ps.STAGE_LABELS[stage]
            default = ps.DEFAULT_STAGE_THRESHOLDS.get(stage, 0)
            tk.Label(grid, text=label, anchor="w",
                      font=("Segoe UI Variable", 10),
                      bg=BG, fg=TEXT_DARK, width=20
                      ).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.IntVar(value=int(current.get(stage, default)))
            spin = tk.Spinbox(grid, from_=0, to=9999, width=6,
                               textvariable=var,
                               font=("Segoe UI Variable", 10))
            spin.grid(row=i, column=1, padx=(8, 4), pady=2)
            tk.Label(grid,
                      text=f"days  (default {default})",
                      font=("Segoe UI Variable", 8),
                      bg=BG, fg=TEXT_GRAY
                      ).grid(row=i, column=2, sticky="w", pady=2)
            spin_vars[stage] = var

        def _save():
            for stage, var in spin_vars.items():
                try:
                    val = int(var.get())
                except (tk.TclError, ValueError):
                    continue
                default = ps.DEFAULT_STAGE_THRESHOLDS.get(stage, 0)
                if val == default:
                    ps.set_threshold(stage, None)  # clear override
                else:
                    ps.set_threshold(stage, val)
            dlg.destroy()
            self._load()
            try:
                show_toast(self, "Thresholds saved", kind="success",
                            duration=1800)
            except Exception:
                pass

        def _reset_all():
            for stage, var in spin_vars.items():
                var.set(ps.DEFAULT_STAGE_THRESHOLDS.get(stage, 0))

        br = tk.Frame(wf, bg=BG)
        br.pack(fill="x", pady=(14, 0))
        tk.Button(br, text="Cancel",
                   font=("Segoe UI Variable", 9), bg=SURFACE_2,
                   fg=TEXT_DARK, relief="flat", padx=12, pady=4,
                   command=dlg.destroy).pack(side="left")
        tk.Button(br, text="Reset to defaults",
                   font=("Segoe UI Variable", 9), bg=SURFACE_2,
                   fg=TEXT_DARK, relief="flat", padx=10, pady=4,
                   command=_reset_all).pack(side="left", padx=(8, 0))
        tk.Button(br, text="Save",
                   font=("Segoe UI Variable", 9, "bold"),
                   bg=GREEN, fg=WHITE, activebackground=GREEN_DARK,
                   relief="flat", padx=14, pady=4,
                   command=_save).pack(side="right")

    def _export_to_excel(self):
        """Write the currently-loaded pipeline rows to an .xlsx with
        one sheet per stage. Uses the current filter window (active +
        paid-within-30d) — what you see in the panel is what gets
        exported."""
        if not self._rows:
            try:
                show_toast(self, "Nothing to export yet — sync first",
                            kind="warning", duration=2200)
            except Exception:
                pass
            return
        from tkinter import filedialog
        default_name = (f"Pipeline {_dt.date.today().month}-"
                        f"{_dt.date.today().day}-"
                        f"{_dt.date.today().year % 100}.xlsx")
        path = filedialog.asksaveasfilename(
            title="Export pipeline",
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("All", "*.*")])
        if not path:
            return
        try:
            import openpyxl
        except ImportError:
            messagebox.showerror(
                "openpyxl missing",
                "openpyxl isn't installed — can't write the workbook.",
                parent=self)
            return
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        headers = ("Client", "Stage", "Days in Stage", "Age",
                    "Last Activity", "Owner", "Board", "Lane", "URL")
        for stage in ps.STAGES:
            sheet_rows = [r for r in self._rows
                          if (r.get("current_stage") or "") == stage]
            ws = wb.create_sheet(title=ps.STAGE_LABELS[stage][:31])
            ws.append(headers)
            for r in sheet_rows:
                ws.append((
                    r.get("client_display") or "",
                    ps.STAGE_LABELS.get(stage, stage),
                    ps.days_in_stage(r),
                    ps.days_since_created(r),
                    (r.get("last_activity_at") or "")[:10],
                    r.get("owner") or "",
                    r.get("board_name") or "",
                    r.get("list_name") or "",
                    r.get("card_url") or "",
                ))
        try:
            wb.save(path)
        except Exception as ex:
            messagebox.showerror(
                "Export failed",
                f"{type(ex).__name__}: {ex}", parent=self)
            return
        try:
            show_toast(self,
                        f"Exported {len(self._rows)} jobs",
                        kind="success", duration=2500)
        except Exception:
            pass


def main(argv=None):
    run_standalone(PipelineApp)


if __name__ == "__main__":
    main()
