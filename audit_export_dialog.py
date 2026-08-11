"""Tk job-picker dialog for the audit PDF export.

Lived in `audit_export` — a module the web panels import for its pure
export/backlog helpers. The dialog is Tk UI and only ever had Tk
callers (run_audit_gui, print_audit_gui, daily_photos_gui), but its
presence meant `audit_export` failed the "pure logic never reaches into
the Tk stack" rule and made that rule un-assertable.

`audit_export` re-exports `open_export_window` lazily via its module
__getattr__, so `audit_export.open_export_window(...)` still works for
every existing caller and nothing had to change at the call sites.
"""
import os

from audit_export import _build_pdf, _OUTPUT_DIR


def open_export_window(parent, results, run_date="", on_close=None):
    """Open job-selection dialog then generate the PDF."""
    import tkinter as tk
    from tkinter import messagebox
    from theme import (BG, WHITE, GREEN, GREEN_DARK, TEXT_DARK, BORDER,
                       FLAG_RED)
    from ui_buttons import done_button
    import theme as _theme
    if not results:
        messagebox.showinfo("Nothing to Export", "No jobs to export.", parent=parent)
        if on_close:
            on_close()
        return

    win = tk.Toplevel(parent)
    win.title("Export Audit PDF")
    win.geometry("560x600")
    win.configure(bg=BG)
    win.resizable(False, True)
    win.grab_set()
    win.protocol("WM_DELETE_WINDOW",
                 lambda: (on_close() if on_close else None, win.destroy()))

    # Header
    n_flagged = sum(1 for r in results if r["flagged"])
    n_ok      = len(results) - n_flagged
    hdr = tk.Frame(win, bg=GREEN, pady=12)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Export Audit PDF",
             font=("Fraunces", 15, "bold"), bg=GREEN, fg=WHITE).pack()
    tk.Label(hdr, text=f"{n_flagged} flagged  ·  {n_ok} OK  ·  Uncheck to exclude",
             font=("Segoe UI Variable", 9), bg=GREEN, fg="#B2DFC4").pack(pady=(2, 0))

    # Scrollable job list
    outer = tk.Frame(win, bg=BG, padx=12, pady=8)
    outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(outer, bg=WHITE, highlightthickness=1,
                       highlightbackground=BORDER)
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    _theme.style_tk_scrollbar(sb)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=WHITE)
    cw = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
        lambda e: canvas.itemconfig(cw, width=e.width))

    def _scroll(e):
        canvas.yview_scroll(-1 * (e.delta // 120), "units")
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _scroll))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    job_vars = []

    # Flagged first, then OK
    for r in sorted(results, key=lambda r: (0 if r["flagged"] else 1)):
        var = tk.BooleanVar(value=True)
        job_vars.append((r, var))

        row = tk.Frame(inner, bg=WHITE, pady=5)
        row.pack(fill="x", padx=8)

        tk.Checkbutton(row, variable=var, bg=WHITE,
                       activebackground=WHITE,
                       selectcolor=WHITE).pack(side="left")

        badge_bg = FLAG_RED if r["flagged"] else GREEN
        tk.Label(row, text="FLAG" if r["flagged"] else " OK ",
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=badge_bg, fg=WHITE, padx=3).pack(side="left", padx=(2, 6))

        name = r["client"]
        if r.get("folder") and r["folder"].lower() != r["client"].lower():
            name += f"  ({r['folder']})"
        if not r.get("found", True):
            name += "  — folder not found"
        tk.Label(row, text=name, font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w").pack(side="left",
                                                           fill="x", expand=True)

        # Issue bullets for flagged jobs
        if r["flagged"]:
            issues = (list(r.get("form_issues") or [])
                      + list(r.get("photo_issues") or [])
                      + list(r.get("note_issues") or []))
            for m in (r.get("missing") or []):
                issues.append(f"Empty folder: {m}")
            if r.get("new_loss"):
                issues.append("New loss — setup not complete yet")
            if r.get("aging", 0) >= 3 and r.get("found", True):
                last_s = r["last"].strftime("%m/%d/%y") if r.get("last") else "never"
                issues.append(f"{r['aging']}d inactive (last: {last_s})")
            for issue in issues:
                det = tk.Frame(inner, bg=WHITE)
                det.pack(fill="x", padx=36)
                tk.Label(det, text=f"☐  {issue}",
                         font=("Segoe UI Variable", 8), bg=WHITE,
                         fg=FLAG_RED, anchor="w").pack(fill="x")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")

    # Bottom bar
    bot = tk.Frame(win, bg=BG, padx=12, pady=10)
    bot.pack(fill="x")

    sel_var = tk.BooleanVar(value=True)
    def _toggle_all():
        v = sel_var.get()
        for _, jv in job_vars:
            jv.set(v)
    tk.Checkbutton(bot, text="Select All", variable=sel_var,
                   font=("Segoe UI Variable", 9), bg=BG, activebackground=BG,
                   selectcolor=WHITE, command=_toggle_all).pack(side="left")

    def _generate():
        chosen = [r for r, v in job_vars if v.get()]
        if not chosen:
            messagebox.showerror("Nothing Selected",
                                 "Select at least one job.", parent=win)
            return
        fname = f"EMS_Audit_{datetime.today().strftime('%m-%d-%Y')}.pdf"
        out   = os.path.join(_OUTPUT_DIR, fname)
        try:
            _build_pdf(chosen, run_date, out)
        except Exception as ex:
            messagebox.showerror("PDF Error", str(ex), parent=win)
            return
        win.destroy()
        if on_close:
            on_close()
        os.startfile(out)

    done_button(bot, "Generate PDF",
                 padx=16, pady=6,
                 command=_generate).pack(side="right")
