"""Shared "Flag missing item" dialog.

Both Initial Upload Queue and Snapshot expose a 📌 Flag missing… button
on each row. They share this dialog so the user experiences one
consistent shape for "I see something missing — track it." The dialog
hands off to missing_items_tracker.capture_missing_items with the
appropriate `stage` so the Trello comment, the Hygiene panel chip, and
the audit trail all attribute the gap to the right step in the
workflow.

Usage:
    import flag_missing_dialog as fmd

    fmd.open_flag_dialog(
        parent,
        client="Smith, John",
        card_id="abc123",
        card_url="https://trello.com/c/abc123",
        tech_initials="FB",
        stage="initial",     # or "snapshot"
        on_submitted=lambda ids: self._refresh(),
    )

The dialog is modal-on-parent so the caller can pop it from a row
button without worrying about lifecycle. `on_submitted` fires once
after the capture call returns (success path only).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from theme import (
    BG, BORDER, WHITE, TEXT_DARK, TEXT_GRAY, GREEN, GREEN_DARK,
    SURFACE_2, NEUTRAL_HOVER, ON_ACCENT,
    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
    WARN_BG, WARN_FG, WARN_HOVER,
    INFO_BG, INFO_FG,
)
from ui_buttons import done_button, secondary_button, chip_label


# Predefined checkboxes — same canonical keys missing_items_tracker
# already labels. Free-text "Other" lives at the bottom for anything
# that doesn't map to a canonical item (e.g. "Equipment log",
# "Moisture map").
_PRESETS = [
    ("atp",            "ATP form"),
    ("cif",            "CIF form"),
    ("cer",            "CER form"),
    ("cos",            "COS form"),
    ("scope",          "Scope"),
    ("sketch",         "Sketch"),
    ("initial_photos", "Initial photos"),
    ("demo_photos",    "Demo photos"),
    ("final_photos",   "Final photos"),
    ("post_photos",    "Post photos"),
]

_STAGE_TITLE = {
    "initial":  "Flag missing — Initial Upload",
    "snapshot": "Flag missing — Snapshot",
    "audit":    "Flag missing — Audit",
    "manual":   "Flag missing item",
}
_STAGE_CHIP_KIND = {
    "initial":  "info",
    "snapshot": "warn",
    "audit":    "ok",
    "manual":   "muted",
}
_STAGE_CHIP_TEXT = {
    "initial":  "INITIAL UPLOAD",
    "snapshot": "SNAPSHOT",
    "audit":    "AUDIT",
    "manual":   "OFFICE",
}


def open_flag_dialog(parent, *, client: str, card_id: str = "",
                     card_url: str = "", tech_initials: str = "",
                     stage: str = "manual",
                     on_submitted=None) -> None:
    """Pop the modal "Flag missing item(s)" dialog for `client`.

    `stage` controls the title, the chip badge, and which `stage` value
    gets recorded on each created tracker entry. `on_submitted` runs
    after a successful capture with the list of created request IDs
    (empty if the user picked nothing → submit is disabled in that
    case, so this is effectively non-empty)."""
    client = (client or "").strip()
    if not client:
        messagebox.showerror(
            "No client", "Can't flag — no client name on this row.",
            parent=parent)
        return

    stage = (stage or "manual").lower()
    title = _STAGE_TITLE.get(stage, _STAGE_TITLE["manual"])

    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=BG)
    dlg.transient(parent)
    dlg.grab_set()
    try:
        dlg.geometry("460x520")
    except tk.TclError:
        pass

    # ── Header ────────────────────────────────────────────────────────
    hdr = tk.Frame(dlg, bg=BG, padx=18, pady=14)
    hdr.pack(fill="x")
    title_row = tk.Frame(hdr, bg=BG)
    title_row.pack(fill="x")
    tk.Label(title_row, text="📌 Flag missing item",
             font=("Fraunces", 16, "bold"),
             bg=BG, fg=TEXT_DARK).pack(side="left")
    chip_label(title_row, _STAGE_CHIP_TEXT.get(stage, "OFFICE"),
               kind=_STAGE_CHIP_KIND.get(stage, "muted")
               ).pack(side="right", padx=(8, 0))

    tk.Label(hdr, text=client,
             font=("Segoe UI Variable", 11),
             bg=BG, fg=TEXT_GRAY, anchor="w"
             ).pack(fill="x", pady=(2, 0))
    tk.Label(hdr,
             text=("Pick what's missing — a Trello comment will tag the "
                   "tech and the gap will show up in Hygiene until "
                   "resolved."),
             font=("Segoe UI Variable", 9),
             bg=BG, fg=TEXT_GRAY,
             wraplength=420, justify="left", anchor="w"
             ).pack(fill="x", pady=(4, 0))

    # ── Preset checkboxes ─────────────────────────────────────────────
    body = tk.Frame(dlg, bg=WHITE, padx=18, pady=14,
                     highlightthickness=0)
    body.pack(fill="both", expand=True, padx=14, pady=(0, 8))
    tk.Label(body, text="Missing items",
             font=("Segoe UI Variable", 10, "bold"),
             bg=WHITE, fg=TEXT_DARK, anchor="w"
             ).pack(fill="x", pady=(0, 6))

    sel_vars: dict[str, tk.BooleanVar] = {}
    grid = tk.Frame(body, bg=WHITE)
    grid.pack(fill="x")
    for i, (key, label) in enumerate(_PRESETS):
        v = tk.BooleanVar(value=False)
        sel_vars[key] = v
        cb = tk.Checkbutton(
            grid, text=label, variable=v,
            font=("Segoe UI Variable", 10),
            bg=WHITE, fg=TEXT_DARK,
            activebackground=WHITE,
            selectcolor=SURFACE_2,
            anchor="w", padx=2, pady=2,
            command=lambda: _refresh_submit_state())
        cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 14))

    # ── Free-text "Other" ─────────────────────────────────────────────
    tk.Label(body, text="Other (free text)",
             font=("Segoe UI Variable", 10, "bold"),
             bg=WHITE, fg=TEXT_DARK, anchor="w"
             ).pack(fill="x", pady=(12, 4))
    other_var = tk.StringVar()
    other_var.trace_add("write", lambda *_: _refresh_submit_state())
    other_ent = ttk.Entry(body, textvariable=other_var,
                            font=("Segoe UI Variable", 10))
    other_ent.pack(fill="x")
    tk.Label(body,
             text='e.g. "Moisture map", "Equipment log"',
             font=("Segoe UI Variable", 8),
             bg=WHITE, fg=TEXT_GRAY,
             anchor="w").pack(fill="x", pady=(2, 0))

    # ── Optional note ─────────────────────────────────────────────────
    tk.Label(body, text="Note (optional)",
             font=("Segoe UI Variable", 10, "bold"),
             bg=WHITE, fg=TEXT_DARK, anchor="w"
             ).pack(fill="x", pady=(12, 4))
    note_txt = tk.Text(body, height=3, wrap="word",
                        font=("Segoe UI Variable", 10),
                        bg=SURFACE_2, fg=TEXT_DARK,
                        relief="flat", padx=8, pady=6,
                        highlightthickness=1,
                        highlightbackground=BORDER)
    note_txt.pack(fill="x")
    tk.Label(body,
             text="Appended to the Trello comment so the tech sees context.",
             font=("Segoe UI Variable", 8),
             bg=WHITE, fg=TEXT_GRAY,
             anchor="w").pack(fill="x", pady=(2, 0))

    # ── Footer ────────────────────────────────────────────────────────
    bot = tk.Frame(dlg, bg=BG, padx=18, pady=12)
    bot.pack(fill="x", side="bottom")

    submit_btn_holder = [None]   # filled below — closures need a handle

    def _selected_items() -> list[str]:
        out: list[str] = []
        for key, v in sel_vars.items():
            if v.get():
                out.append(key)
        other = (other_var.get() or "").strip()
        if other:
            out.append(other)
        return out

    def _refresh_submit_state(*_):
        n = len(_selected_items())
        btn = submit_btn_holder[0]
        if not btn:
            return
        try:
            btn.config(
                text=(f"📌 Flag {n} item{'s' if n != 1 else ''}"
                       if n else "📌 Flag missing"),
                state=("normal" if n else "disabled"))
        except tk.TclError:
            pass

    def _submit():
        items = _selected_items()
        if not items:
            return
        note = (note_txt.get("1.0", "end") or "").strip()
        try:
            import missing_items_tracker as mit
            ids = mit.capture_missing_items(
                client,
                card_id=card_id, card_url=card_url,
                missing=items,
                tech_initials=tech_initials,
                stage=stage, note=note)
        except Exception as ex:
            messagebox.showerror(
                "Tracker error",
                f"Could not flag the missing item(s):\n\n{ex}",
                parent=dlg)
            return
        try:
            from tool_panel import show_toast
            show_toast(
                parent,
                f"Flagged {len(ids)} item(s) for {client} — "
                f"tracked in Hygiene.", kind="info", duration=3000)
        except Exception:
            pass
        if on_submitted:
            try:
                on_submitted(ids)
            except Exception:
                pass
        dlg.destroy()

    secondary_button(bot, "Cancel", command=dlg.destroy
                      ).pack(side="right", padx=(6, 0))
    submit_btn_holder[0] = done_button(
        bot, "📌 Flag missing", command=_submit)
    submit_btn_holder[0].pack(side="right")
    submit_btn_holder[0].config(state="disabled")

    _refresh_submit_state()
    try:
        dlg.update_idletasks()
        # Center on parent
        px = parent.winfo_rootx() + (parent.winfo_width() // 2)
        py = parent.winfo_rooty() + (parent.winfo_height() // 2)
        dw = dlg.winfo_width()
        dh = dlg.winfo_height()
        dlg.geometry(f"+{px - dw // 2}+{py - dh // 2}")
    except tk.TclError:
        pass
    dlg.wait_window()
