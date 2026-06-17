"""Standalone Scope dialog — paste a Trello-style room-by-room block,
parse it, and save a Scope.pdf into the job's EMS/DOCS folder.

Used by:
- snapshot_gui (existing wired-up flow inside the snapshot tool)
- run_audit_gui (the manual "📋 Scope" button on rows where Scope is
  the missing form — Scope isn't uploaded via Workcenter so a link
  doesn't help; this lets the user generate one in place).

Implementation note: parse_scope and build_scope_pdf live in
snapshot_gui as free functions, so we import them here. snapshot_gui
does NOT import this module, so no cycle.
"""
import os
import tkinter as tk
from tkinter import messagebox

from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, BORDER,
                    SURFACE_2, ON_ACCENT)
from ui_buttons import done_button, send_button, secondary_button


def open_scope_dialog(parent, insured, job_path, initial_rooms=None,
                       on_saved=None):
    """Open the Scope preview/paste dialog.

    insured: client name used in the PDF title and output filename.
    job_path: root job folder; PDF is written to <job>/EMS/DOCS/ if EMS
              exists, otherwise <job>/DOCS/.
    initial_rooms: optional pre-parsed list (skips the paste step).
    on_saved: optional callback(out_path) fired after a successful save,
              before the PDF is opened. Lets the caller mark the issue
              resolved on its own UI.
    """
    # Imported lazily — snapshot_gui touches the config at import time, so
    # loading it eagerly would force every test/caller to provide that key.
    from snapshot_gui import parse_scope, build_scope_pdf

    rooms = list(initial_rooms or [])

    dlg = tk.Toplevel(parent)
    dlg.title("Scope Preview")
    dlg.geometry("520x480")
    dlg.configure(bg=BG)
    dlg.resizable(False, True)
    dlg.grab_set()

    hdr = tk.Frame(dlg, bg=GREEN, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Scope Preview", font=("Segoe UI Variable", 12, "bold"),
             bg=GREEN, fg=WHITE).pack()
    tk.Label(hdr, text=insured, font=("Segoe UI Variable", 9),
             bg=GREEN, fg="#B2DFC4").pack()

    outer = tk.Frame(dlg, bg=BG, padx=12, pady=8)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=WHITE, highlightthickness=1,
                       highlightbackground=BORDER)
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    try:
        import theme as _theme
        _theme.style_tk_scrollbar(sb)
    except Exception:
        pass
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=WHITE, padx=10, pady=8)
    cw = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
        lambda e: canvas.itemconfig(cw, width=e.width))
    def _scroll(e): canvas.yview_scroll(-1*(e.delta//120), "units")
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _scroll))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _render_rooms():
        for w in inner.winfo_children():
            w.destroy()
        if rooms:
            for room_data in rooms:
                tk.Label(inner, text=room_data["room"],
                         font=("Segoe UI Variable", 9, "bold"), bg=WHITE,
                         fg=TEXT_DARK, anchor="w").pack(fill="x", pady=(6, 2))
                for item in room_data["items"]:
                    tk.Label(inner, text=f"  {item}",
                             font=("Segoe UI Variable", 8), bg=WHITE,
                             fg=TEXT_DARK, anchor="w").pack(fill="x")
        else:
            tk.Label(inner,
                     text="Paste the scope notes below and click Parse:",
                     font=("Segoe UI Variable", 9), bg=WHITE, fg=TEXT_DARK,
                     justify="left", wraplength=460).pack(anchor="w", pady=(8, 4))
            paste_box = tk.Text(inner, height=12, font=("Consolas", 8),
                                bg=SURFACE_2, relief="flat", borderwidth=1,
                                highlightthickness=1, highlightbackground=BORDER,
                                wrap="word")
            paste_box.pack(fill="x", pady=(0, 6))

            def _parse_pasted():
                raw = paste_box.get("1.0", tk.END).strip()
                if not raw:
                    messagebox.showwarning("Empty",
                        "Paste some scope text first.", parent=dlg)
                    return
                parsed = parse_scope(raw)
                if not parsed:
                    messagebox.showwarning("Not Parsed",
                        "Could not detect a room-by-room scope in that text.\n\n"
                        "Make sure it follows the scope format from Trello.",
                        parent=dlg)
                    return
                rooms[:] = parsed
                _render_rooms()

            send_button(inner, "Parse Scope",
                         command=_parse_pasted
                         ).pack(anchor="e", pady=(0, 6))

    _render_rooms()

    bot = tk.Frame(dlg, bg=BG, padx=12, pady=10)
    bot.pack(fill="x")
    secondary_button(bot, "Close",
                      command=dlg.destroy).pack(side="left")

    def _save():
        if not rooms:
            messagebox.showwarning("No Scope Data",
                "Parse the scope first before saving.", parent=dlg)
            return
        ems  = os.path.join(job_path, "EMS")
        base = ems if os.path.isdir(ems) else job_path
        docs = os.path.join(base, "DOCS")
        os.makedirs(docs, exist_ok=True)
        out  = os.path.join(docs, "Scope.pdf")
        try:
            build_scope_pdf(rooms, insured, out)
        except Exception as ex:
            messagebox.showerror("PDF Error", str(ex), parent=dlg)
            return
        if on_saved is not None:
            try:
                on_saved(out)
            except Exception:
                pass
        # Auto-tick PRELIMINARY SCOPE on the pinned Trello card now
        # that Scope.pdf is on disk.
        try:
            import persistence as _per
            _card_id = (_per.get_trello_card_id(insured) or ""
                         if insured else "")
            if _card_id:
                import trello_autotick as _at
                _at.autotick(_card_id, events=("scope_saved",),
                             client=insured)
        except Exception:
            pass
        dlg.destroy()
        os.startfile(out)

    done_button(bot, "Save PDF to EMS Docs", padx=16, pady=6,
                 command=_save).pack(side="right")
