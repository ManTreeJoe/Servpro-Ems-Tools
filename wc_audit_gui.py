"""Monthly WC Audit panel.

Workflow:
  1. Pick the WC export Excel from Downloads.
  2. Background classifier walks every in-scope Trello board and buckets
     each WC row into one of five categories (Active EMS, Recon,
     Estimating, Not sold, Pending approvals).
  3. Operator reviews the five tabs; right-click → Move to another tab
     handles edge cases the auto-classifier got wrong.
  4. Save & Send writes ``WC audit M-D-YY.xlsx`` to the shared share and
     opens a Teams chat to Sam with the file path prefilled.
"""
from __future__ import annotations

import datetime
import os
import threading
import tkinter as tk
import urllib.parse
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

from theme import (BG, BORDER, GREEN, GREEN_DARK, INFO_BG, INFO_FG,
                    SURFACE_2, TEXT_DARK, TEXT_GRAY, WARN_BG, WARN_FG,
                    WHITE)
from tool_panel import ToolPanel, run_standalone, show_toast
from ui_buttons import done_button, secondary_button

import wc_audit


DOWNLOADS = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
SAM_EMAIL_KEY = "wc_audit_sam_email"


class WCMonthlyAuditApp(ToolPanel):
    TOOL_TITLE = "Monthly WC Audit"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_path = ""
        # Single in-memory row list — each row dict carries ``_cat`` and
        # ``assignee`` fields, so moving rows between buckets is just a
        # field update plus tab re-render. The Treeview iid -> row dict
        # mapping lets right-click context actions find the underlying
        # row from the tree selection.
        self._rows: list[dict] = []
        self._row_by_iid: dict[str, dict] = {}
        self._tree_by_cat: dict[str, ttk.Treeview] = {}
        self._build_ui()

    # ── UI scaffold ──────────────────────────────────────────────────────
    def _build_ui(self):
        head = tk.Frame(self, bg=BG, padx=20, pady=12)
        head.pack(fill="x")
        tk.Label(head, text="🗂  Monthly WC Audit",
                  font=("Fraunces", 16, "bold"),
                  bg=BG, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(head,
                  text=("Pick the WC export from Downloads → "
                        "classify by Trello status → review tabs → "
                        "send to Sam."),
                  font=("Segoe UI Variable", 9),
                  bg=BG, fg=TEXT_GRAY).pack(anchor="w", pady=(2, 0))

        bar = tk.Frame(self, bg=BG, padx=20, pady=6)
        bar.pack(fill="x")
        done_button(bar, "📂  Pick WC export…",
                    command=self._pick_and_load).pack(side="left")
        self._status_lbl = tk.Label(
            bar, text="",
            font=("Segoe UI Variable", 9, "italic"),
            bg=BG, fg=TEXT_GRAY)
        self._status_lbl.pack(side="left", padx=(12, 0))

        self._save_btn = secondary_button(
            bar, "💾  Save & Send to Sam",
            command=self._save_and_send)
        self._save_btn.pack(side="right")
        try:
            self._save_btn.config(state="disabled")
        except tk.TclError:
            pass

        # Tabbed body — one tab per bucket. Tabs are rebuilt on every load.
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=20, pady=(6, 14))

    # ── Load / classify ──────────────────────────────────────────────────
    def _pick_and_load(self):
        initial = DOWNLOADS if os.path.isdir(DOWNLOADS) else None
        path = filedialog.askopenfilename(
            title="Pick the WC export",
            initialdir=initial,
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
        if not path:
            return
        self._source_path = path
        self._status_lbl.config(
            text=f"Loading {os.path.basename(path)}…")
        try:
            self._save_btn.config(state="disabled")
        except tk.TclError:
            pass

        def _bg():
            err = None
            rows = []
            try:
                rows = wc_audit.load_source(path)

                def _progress(i, n, board_name):
                    try:
                        self.after(0,
                                    lambda: self._status_lbl.config(
                                        text=(f"Scanning Trello "
                                              f"{i}/{n}: "
                                              f"{board_name}…")))
                    except Exception:
                        pass

                idx = wc_audit.build_trello_index(progress_cb=_progress)
                wc_audit.bucket_rows(rows, idx)
            except Exception as ex:
                err = ex

            def _done():
                if err is not None:
                    messagebox.showerror(
                        "Load failed",
                        f"Couldn't load + classify the WC export:\n\n"
                        f"{type(err).__name__}: {err}",
                        parent=self)
                    self._status_lbl.config(text="")
                    return
                self._rows = rows
                self._render_tabs()
                total = len(rows)
                by_cat = {
                    cat: len(wc_audit.rows_for_cat(rows, cat))
                    for cat in wc_audit.CATEGORIES
                }
                summary = "  ·  ".join(
                    f"{wc_audit.CATEGORY_LABELS[c]}: {by_cat[c]}"
                    for c in wc_audit.CATEGORIES)
                self._status_lbl.config(
                    text=f"{total} rows  ·  {summary}")
                try:
                    self._save_btn.config(state="normal")
                except tk.TclError:
                    pass

            try:
                self.after(0, _done)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    # ── Tab rendering ────────────────────────────────────────────────────
    def _render_tabs(self):
        for tab_id in list(self._notebook.tabs()):
            try:
                self._notebook.forget(tab_id)
            except tk.TclError:
                pass
        self._tree_by_cat = {}
        self._row_by_iid = {}
        for cat in wc_audit.CATEGORIES:
            frame = tk.Frame(self._notebook, bg=BG)
            self._notebook.add(frame, text=self._tab_label(cat))
            self._build_tab_body(frame, cat)

    def _tab_label(self, cat):
        n = sum(1 for r in self._rows if r.get("_cat") == cat)
        return f"{wc_audit.CATEGORY_LABELS[cat]} ({n})"

    def _refresh_tab_labels(self):
        for i, cat in enumerate(wc_audit.CATEGORIES):
            try:
                self._notebook.tab(i, text=self._tab_label(cat))
            except tk.TclError:
                pass

    def _build_tab_body(self, parent, cat):
        is_est = (cat == "estimating")
        cols = ("date", "corp", "project", "ptype", "type", "progress",
                 "customer")
        if is_est:
            cols = cols + ("assignee",)
        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             selectmode="extended")
        headers = list(wc_audit.COL_HEADERS)
        if is_est:
            headers.append("Assignee")
        widths = (130, 90, 130, 90, 80, 130, 240)
        if is_est:
            widths = widths + (120,)
        for cid, hdr, w in zip(cols, headers, widths):
            tree.heading(cid, text=hdr)
            tree.column(cid, width=w, anchor="w")

        sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        self._tree_by_cat[cat] = tree

        self._populate_tab(cat)

        # Right-click → move to another bucket. Other-bucket targets are
        # every category except the current one.
        menu = tk.Menu(tree, tearoff=0)
        for target_cat in wc_audit.CATEGORIES:
            if target_cat == cat:
                continue
            menu.add_command(
                label=f"Move to → {wc_audit.CATEGORY_LABELS[target_cat]}",
                command=lambda tc=target_cat, src=cat:
                    self._move_selected(src, tc))
        tree.bind("<Button-3>",
                  lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

        # Inline assignee edit on the Estimating tab — double-click the
        # last column. For other tabs the double-click is a no-op.
        if is_est:
            tree.bind("<Double-1>", self._handle_assignee_dblclick)

    def _populate_tab(self, cat):
        tree = self._tree_by_cat.get(cat)
        if tree is None:
            return
        # Wipe + repopulate. Cheap (each tab has at most ~hundred rows)
        # so a full repaint when rows move is fine.
        for iid in tree.get_children():
            self._row_by_iid.pop(iid, None)
            try:
                tree.delete(iid)
            except tk.TclError:
                pass
        is_est = (cat == "estimating")
        for r in wc_audit.rows_for_cat(self._rows, cat):
            vals = (self._fmt_date(r.get("date_received")),
                     r.get("corp_ref", ""),
                     r.get("project_num", ""),
                     r.get("property_type", ""),
                     r.get("type", ""),
                     r.get("progress", ""),
                     r.get("customer", ""))
            if is_est:
                vals = vals + (r.get("assignee", ""),)
            iid = tree.insert("", "end", values=vals)
            self._row_by_iid[iid] = r

    def _fmt_date(self, v):
        """Render dates the same way the example file does — ISO-style
        truncated to the seconds. Falls through to str() for anything
        the openpyxl loader didn't pick up as a datetime."""
        if v is None:
            return ""
        if hasattr(v, "strftime"):
            try:
                return v.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return str(v)
        return str(v)

    # ── Bucket moves + assignee edit ─────────────────────────────────────
    def _move_selected(self, src_cat, dst_cat):
        tree = self._tree_by_cat.get(src_cat)
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        for iid in sel:
            row = self._row_by_iid.get(iid)
            if row is None:
                continue
            row["_cat"] = dst_cat
            # Clear assignee on rows leaving Estimating so a stale lane
            # name doesn't follow the row into another bucket.
            if src_cat == "estimating" and dst_cat != "estimating":
                row["assignee"] = ""
        self._populate_tab(src_cat)
        self._populate_tab(dst_cat)
        self._refresh_tab_labels()

    def _handle_assignee_dblclick(self, event):
        tree = event.widget
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = tree.identify_column(event.x)  # like "#8"
        # Assignee is the last column on the Estimating tab.
        if col != f"#{len(tree['columns'])}":
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        row = self._row_by_iid.get(iid)
        if row is None:
            return
        current = row.get("assignee", "")
        new = simpledialog.askstring(
            "Assignee",
            f"Estimator for {row.get('customer') or 'this row'}:",
            initialvalue=current, parent=self)
        if new is None:
            return  # cancelled
        row["assignee"] = new.strip()
        self._populate_tab("estimating")

    # ── Save + send ──────────────────────────────────────────────────────
    def _save_and_send(self):
        if not self._rows:
            return
        out_path = wc_audit.default_output_path()
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except OSError as ex:
            messagebox.showerror(
                "Output dir unreachable",
                f"Couldn't create / reach\n{os.path.dirname(out_path)}\n\n"
                f"{type(ex).__name__}: {ex}",
                parent=self)
            return
        if os.path.exists(out_path):
            if not messagebox.askyesno(
                    "Overwrite?",
                    f"{os.path.basename(out_path)} already exists.\n\n"
                    "Overwrite it?",
                    parent=self):
                return
        try:
            wc_audit.write_workbook(self._rows, out_path)
        except Exception as ex:
            messagebox.showerror(
                "Save failed",
                f"Couldn't write the workbook:\n\n"
                f"{type(ex).__name__}: {ex}",
                parent=self)
            return
        try:
            show_toast(self,
                        f"Saved {os.path.basename(out_path)}",
                        kind="success", duration=2500)
        except Exception:
            pass
        self._open_teams_to_sam(out_path)

    def _open_teams_to_sam(self, file_path):
        try:
            import persistence as per
            email = (per.get(SAM_EMAIL_KEY) or "").strip()
        except Exception:
            email = ""
        if not email:
            email = self._ask_sam_email() or ""
            if not email:
                messagebox.showinfo(
                    "Saved",
                    f"File saved to:\n{file_path}\n\n"
                    "Teams skipped (no Sam email on file).",
                    parent=self)
                return
        msg = (f"Monthly WC Audit ready for review.\n\n"
               f"File: {file_path}")
        url = ("msteams:/l/chat/0/0?users=" +
               urllib.parse.quote(email, safe="") +
               "&message=" + urllib.parse.quote(msg, safe=""))
        try:
            webbrowser.open(url)
        except Exception:
            messagebox.showinfo(
                "Saved",
                f"File saved to:\n{file_path}\n\n"
                "Couldn't open Teams — send the file path to Sam manually.",
                parent=self)

    def _ask_sam_email(self):
        email = simpledialog.askstring(
            "Sam's Teams email",
            "Enter Sam's Teams email (saved for next time):",
            parent=self)
        if not email:
            return ""
        email = email.strip()
        try:
            import persistence as per
            per.set_value(SAM_EMAIL_KEY, email)
        except Exception:
            pass
        return email


def main(argv=None):
    run_standalone(WCMonthlyAuditApp)


if __name__ == "__main__":
    main()
