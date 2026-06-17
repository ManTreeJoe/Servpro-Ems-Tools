import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import os
import re
import shutil
import zipfile
from datetime import datetime

import paths
import config
import ctk_helpers as ctkh
from tool_panel import (ToolPanel, run_standalone,
                         ScrollableFrame, ResponsiveSnap)

_CFG = config.load()
AUDIT_BASE = _CFG["audit_base"]
DOWNLOADS  = os.path.join(os.environ["USERPROFILE"], "Downloads")

from theme import GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY, BORDER, FLAG_RED

JOB_TYPES  = ["PO PB", "EMS", "Contents", "Recon", "PO", "PB", "Other"]
VALID_EXTS = {'.pdf', '.xlsx', '.xlsm', '.xls', '.zip'}

TYPE_LABEL = {
    'xactimate':      'Xactimate PDF',
    'photo_inventory':'Photo Inventory',
    'excel':          'Excel',
    'zip':            'ZIP (Photos)',
    'drybook':        'Dry Book',
    'unknown':        'Unknown',
}
TYPE_COLOR = {
    'xactimate':      '#1A3A6A',
    'photo_inventory':'#2A6A1A',
    'excel':          '#1A5A3A',
    'zip':            '#6A3A1A',
    'drybook':        '#4A1A6A',
    'unknown':        TEXT_GRAY,
}


def _normalize(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-zA-Z ]', ' ', s)).strip().lower()

def _reversed(name):
    parts = name.strip().split()
    return f"{' '.join(parts[1:])} {parts[0]}" if len(parts) >= 2 else name

def _fuzzy(query, candidates):
    q = _normalize(query).split()
    scored = []
    for c in candidates:
        shared = sum(1 for w in q if w in _normalize(c).split())
        if shared:
            scored.append((shared, c))
    return [c for _, c in sorted(scored, reverse=True)]

def _file_type(name):
    nl  = name.lower()
    ext = os.path.splitext(nl)[1]
    if re.search(r'drybook|dry.?book', nl): return 'drybook'
    if ext == '.zip':                        return 'zip'
    if ext in ('.xlsx', '.xlsm', '.xls'):   return 'excel'
    if ext == '.pdf':
        if re.search(r'photo|inventory', nl): return 'photo_inventory'
        return 'xactimate'
    return 'unknown'

def _find_year_folder(base, year, lafire):
    try:
        dirs = [d for d in os.listdir(base)
                if os.path.isdir(os.path.join(base, d))]
    except OSError:
        return None
    if lafire:
        m = next((d for d in dirs if str(year) in d
                  and 'LA' in d.upper() and 'FIRE' in d.upper()), None)
        if not m:
            m = next((d for d in dirs
                      if 'LA' in d.upper() and 'FIRE' in d.upper()), None)
    else:
        m = next((d for d in dirs if str(year) in d
                  and not ('LA' in d.upper() and 'FIRE' in d.upper())), None)
    return os.path.join(base, m) if m else None

def _find_client(year_folder, name):
    """Returns folder name str, list of fuzzy candidates, or None."""
    try:
        dirs = [d for d in os.listdir(year_folder)
                if os.path.isdir(os.path.join(year_folder, d))]
    except OSError:
        return None
    norm = _normalize(name)
    exact = next((d for d in dirs if _normalize(d) == norm), None)
    if exact:
        return exact
    rev = _normalize(_reversed(name))
    exact_rev = next((d for d in dirs if _normalize(d) == rev), None)
    if exact_rev:
        return exact_rev
    hits = _fuzzy(name, dirs)
    return hits if hits else None


class SortFilesApp(ToolPanel):
    TOOL_TITLE = "Sort Files"
    TOOL_AUMID = "Servpro.EMS.SortFiles"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Sort Files")
        self.configure(bg=BG)
        self.resizable(False, False)

        ico = paths.resource("wrench.ico")
        if os.path.exists(ico):
            try:
                img = Image.open(ico)
                ph  = ImageTk.PhotoImage(img)
                self.iconphoto(True, ph)
                self._icon = ph
            except Exception:
                pass

        self.client_var  = tk.StringVar()
        self.jobtype_var = tk.StringVar(value="PO PB")
        self.lafire_var  = tk.BooleanVar()
        self.fnfirst_var = tk.BooleanVar()
        self.year_var    = tk.StringVar(value=str(datetime.today().year))

        self._year_folder   = None
        self._client_folder = None
        self._file_vars     = []

        self._build_ui()

    def _build_ui(self):
        self.build_header("SERVPRO  ·  Sort Files",
                          subtitle="Move Downloads into the correct job folder on X:\\",
                          pady=14)

        form = tk.Frame(self, bg=BG, padx=20, pady=14)
        form.pack(fill="x")

        ctkh.h2(form, "Client name").grid(row=0, column=0, sticky="w", pady=4)
        client_entry = ctkh.entry(form, textvariable=self.client_var, width=240)
        client_entry.grid(row=0, column=1, padx=8, sticky="w")
        client_entry.bind("<Return>", lambda e: self._find_client())
        ctkh.btn(form, "Find  ›", command=self._find_client, kind="primary",
                 width=80).grid(row=0, column=2)

        ctkh.h2(form, "Job type").grid(row=1, column=0, sticky="w", pady=4)
        ctkh.combobox(form, JOB_TYPES, variable=self.jobtype_var,
                      width=140
                      ).grid(row=1, column=1, padx=8, sticky="w")

        ctkh.h2(form, "Year").grid(row=2, column=0, sticky="w", pady=4)
        opt = tk.Frame(form, bg=BG)
        opt.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
        ctkh.entry(opt, textvariable=self.year_var, width=70).pack(side="left")
        ctkh.ctk.CTkSwitch(opt, text="LA Fire", variable=self.lafire_var,
                           font=ctkh.font(10), text_color=TEXT_DARK,
                           progress_color=GREEN, button_color=WHITE,
                           button_hover_color="#F0F0F0"
                           ).pack(side="left", padx=(14, 0))
        ctkh.ctk.CTkSwitch(opt, text="First name first",
                           variable=self.fnfirst_var,
                           font=ctkh.font(10), text_color=TEXT_DARK,
                           progress_color=GREEN, button_color=WHITE,
                           button_hover_color="#F0F0F0"
                           ).pack(side="left", padx=(10, 0))

        self.folder_label = ctkh.ctk.CTkLabel(
            self, text="", font=ctkh.font(9),
            text_color=TEXT_GRAY, anchor="w", justify="left",
            wraplength=500)
        self.folder_label.pack(anchor="w", padx=20, pady=(0, 2))

        ctkh.h2(self, "Files in Downloads").pack(
            anchor="w", padx=20)

        scroll = ScrollableFrame(self, bg=BG, canvas_bg=WHITE, padx=20, pady=4)
        scroll.canvas.config(highlightthickness=1, highlightbackground=BORDER,
                              height=200)
        scroll.pack(fill="both", expand=True)
        self._fcanvas = scroll.canvas
        self._finner  = scroll.inner
        self._fscroll = scroll
        self._finner.config(bg=WHITE)

        tk.Label(self._finner, text="Find a client folder first.",
                 font=("Segoe UI Variable", 9, "italic"),
                 bg=WHITE, fg=TEXT_GRAY, pady=20).pack()

        bot = tk.Frame(self, bg=BG, padx=20, pady=10)
        bot.pack(fill="x")
        self.status_label = ctkh.ctk.CTkLabel(
            bot, text="", font=ctkh.font(10), text_color=TEXT_GRAY)
        self.status_label.pack(side="left")
        ctkh.btn(bot, "Sort Files", command=self._sort, kind="primary",
                 width=120, height=34).pack(side="right")

    def _find_client(self):
        name = self.client_var.get().strip()
        if not name:
            messagebox.showerror("Missing", "Enter a client name.")
            return
        try:
            year = int(self.year_var.get())
        except ValueError:
            messagebox.showerror("Invalid Year", "Enter a valid 4-digit year.")
            return
        if not os.path.exists(AUDIT_BASE):
            messagebox.showerror("Drive Error",
                f"Cannot reach {AUDIT_BASE} — is the X: drive connected?")
            return

        yf = _find_year_folder(AUDIT_BASE, year, self.lafire_var.get())
        if not yf:
            tag = "LA Fire " if self.lafire_var.get() else ""
            messagebox.showerror("Not Found",
                f"No {tag}{year} folder found in {AUDIT_BASE}")
            return

        self._year_folder = yf
        result = _find_client(yf, name)

        if result is None:
            self.folder_label.configure(
                text=f"No match found for '{name}'.", text_color=FLAG_RED)
            self._client_folder = None
            self._refresh_files()
            return

        if isinstance(result, list):
            self._fuzzy_picker(result)
        else:
            self._set_folder(result)

    def _fuzzy_picker(self, matches):
        dlg = tk.Toplevel(self)
        dlg.title("Select Folder")
        dlg.resizable(False, False)
        dlg.grab_set()
        f = tk.Frame(dlg, bg=BG, padx=20, pady=16)
        f.pack()
        tk.Label(f, text="No exact match — pick the correct folder:",
                 font=("Segoe UI Variable", 10, "bold"), bg=BG).pack(anchor="w", pady=(0, 8))
        var = tk.StringVar(value=matches[0])
        for m in matches[:6]:
            tk.Radiobutton(f, text=m, variable=var, value=m,
                           font=("Segoe UI Variable", 9), bg=BG,
                           activebackground=BG).pack(anchor="w", pady=2)
        def _pick():
            chosen = var.get()
            dlg.destroy()
            self._set_folder(chosen)
        ctkh.btn(f, "Select", command=_pick, kind="primary",
                 height=34).pack(pady=(12, 0), fill="x")

    def _set_folder(self, folder_name):
        self._client_folder = os.path.join(self._year_folder, folder_name)
        self.folder_label.configure(text=f"Folder: {folder_name}",
                                    text_color=GREEN_DARK)
        self._refresh_files()

    def _refresh_files(self):
        for w in self._finner.winfo_children():
            w.destroy()
        self._file_vars = []

        if not self._client_folder:
            tk.Label(self._finner, text="Find a client folder first.",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, pady=20).pack()
            return

        try:
            with os.scandir(DOWNLOADS) as it:
                files = sorted(
                    [e for e in it
                     if e.is_file() and
                     os.path.splitext(e.name)[1].lower() in VALID_EXTS],
                    key=lambda e: e.stat().st_mtime, reverse=True
                )
        except OSError:
            tk.Label(self._finner, text="Could not read Downloads folder.",
                     bg=WHITE, fg=FLAG_RED, pady=10).pack()
            return

        if not files:
            tk.Label(self._finner,
                     text="No matching files in Downloads (.pdf / .xlsx / .xlsm / .zip)",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, pady=20).pack()
            return

        for entry in files:
            ftype = _file_type(entry.name)
            var   = tk.BooleanVar(value=(ftype != 'unknown'))
            self._file_vars.append((entry, var))

            row = tk.Frame(self._finner, bg=WHITE)
            row.pack(fill="x", padx=8, pady=2)
            tk.Checkbutton(row, variable=var, bg=WHITE,
                           activebackground=WHITE,
                           selectcolor=WHITE).pack(side="left")
            tk.Label(row, text=entry.name, font=("Segoe UI Variable", 8, "bold"),
                     bg=WHITE, fg=TEXT_DARK, anchor="w"
                     ).pack(side="left", fill="x", expand=True)
            tk.Label(row, text=TYPE_LABEL.get(ftype, ftype),
                     font=("Segoe UI Variable", 8), bg=WHITE,
                     fg=TYPE_COLOR.get(ftype, TEXT_GRAY)
                     ).pack(side="right", padx=8)

        self.status_label.configure(text=f"{len(files)} file(s) found in Downloads")

    def _sort(self):
        if not self._client_folder:
            messagebox.showerror("No Folder", "Find a client folder first.")
            return
        selected = [(e, v) for e, v in self._file_vars if v.get()]
        if not selected:
            messagebox.showerror("Nothing Selected",
                                 "Check at least one file to move.")
            return

        name  = self.client_var.get().strip()
        parts = name.split()
        last  = (parts[-1] if self.fnfirst_var.get() else parts[0]).upper()
        jtype = self.jobtype_var.get()

        sf_c_docs = os.path.join(self._client_folder, "CONTENTS", "DOCS")
        sf_c_pics = os.path.join(self._client_folder, "CONTENTS", "PICS")
        sf_e_docs = os.path.join(self._client_folder, "EMS", "DOCS")
        for p in (sf_c_docs, sf_c_pics, sf_e_docs):
            os.makedirs(p, exist_ok=True)

        xact_sel  = [e for e, _ in selected if _file_type(e.name) == 'xactimate']
        excel_sel = [e for e, _ in selected if _file_type(e.name) == 'excel']

        done, skipped = [], []

        for entry, _ in selected:
            ft = _file_type(entry.name)

            if ft == 'photo_inventory':
                dest = os.path.join(sf_c_docs, "Photo Inventory Report.pdf")
                shutil.copy2(entry.path, dest)
                os.remove(entry.path)
                done.append("Photo Inventory → CONTENTS\\DOCS\\Photo Inventory Report.pdf")

            elif ft == 'xactimate':
                if len(xact_sel) > 1 and entry.path != xact_sel[0].path:
                    skipped.append(f"{entry.name} (extra Xactimate — skipped)")
                else:
                    dest_name = f"{last} {jtype} Estimate.pdf"
                    shutil.copy2(entry.path, os.path.join(sf_c_docs, dest_name))
                    os.remove(entry.path)
                    done.append(f"Xactimate → CONTENTS\\DOCS\\{dest_name}")

            elif ft == 'excel':
                if len(excel_sel) > 1 and entry.path != excel_sel[0].path:
                    skipped.append(f"{entry.name} (extra Excel — skipped)")
                else:
                    for ext in ('.xlsx', '.xlsm'):
                        dest_name = f"{last}FinalCalculation{ext}"
                        shutil.copy2(entry.path,
                                     os.path.join(sf_c_docs, dest_name))
                        done.append(f"Excel → CONTENTS\\DOCS\\{dest_name}")
                    os.remove(entry.path)

            elif ft == 'zip':
                with zipfile.ZipFile(entry.path, 'r') as z:
                    z.extractall(sf_c_pics)
                os.remove(entry.path)
                done.append(f"{entry.name} → extracted to CONTENTS\\PICS\\")

            elif ft == 'drybook':
                shutil.move(entry.path, os.path.join(sf_e_docs, entry.name))
                done.append(f"{entry.name} → EMS\\DOCS\\")

            else:
                skipped.append(f"{entry.name} (unknown type — skipped)")

        self._refresh_files()
        self.status_label.configure(text=f"{len(done)} file(s) moved.")

        msg = f"{len(done)} file(s) moved.\n\n" + "\n".join(done)
        if skipped:
            msg += f"\n\nSkipped ({len(skipped)}):\n" + "\n".join(skipped)
        messagebox.showinfo("Sort Complete", msg)


def main(argv=None):
    run_standalone(SortFilesApp, geometry="560x680", resizable=(False, False))


if __name__ == "__main__":
    main()
