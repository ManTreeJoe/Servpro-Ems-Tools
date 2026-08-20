"""One-click "Process card" dialog for the Initial Upload Queue.

Collapses the typical end-of-intake ritual into a single click + a
confirmation step:

  1. Scaffold the EMS / EMS/DOCS / EMS/PICS folder structure if any
     of the three is missing on disk.
  2. (Optional) Trigger the SP import flow for the card so any photos
     already on SharePoint get pulled into PICS/Initial.
  3. Auto-tick every Trello checklist item whose artifact is present
     in the OD folder (INITIAL PAPERWORK if EMS/DOCS has any forms,
     INITIAL PHOTOS if PICS/Initial has any images, PHYSICAL SKETCH
     if a Docusketch subfolder exists, PRELIMINARY SCOPE if Scope.pdf
     is on disk).
  4. Post the canonical "Initial Upload submitted To WC." comment to
     Trello.
  5. Tick the gating INITIAL UPLOAD checklist item (which drops the
     card off the IUQ).

Each step has a checkbox in the dialog; defaults pre-tick based on
what's actually detected on disk. User can opt out of any step (e.g.
skip SP import when they know the tech hasn't uploaded yet).

Caller passes a `card` dict (must contain `card_id`, `client`,
`job_path`) and an `audit_app` reference (the parent RunAuditApp that
hosts SP import). When `audit_app` is None the SP step is hidden — the
embedded IUQ-only mode can't trigger the SP dialog without the audit
panel.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

from theme import (
    BG, BORDER, WHITE, TEXT_DARK, TEXT_GRAY, SURFACE_2,
    SUCCESS_FG, WARN_FG, FLAG_RED, GREEN,
)
from ui_buttons import done_button, secondary_button, chip_label


# Canonical confirmation comment posted at the end of the flow.
_CANONICAL_COMMENT = "Initial Upload submitted To WC."

# Image extensions used for the "any photos under PICS/Initial?" check.
# Same set the rest of the suite uses for SP / WC photo detection.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp",
               ".bmp", ".tif", ".tiff", ".gif",
               ".mp4", ".mov", ".m4v", ".avi"}


def _has_initial_forms(folder: str) -> bool:
    """True when EMS/DOCS holds an actual intake form (ATP/CIF/CER/COS).

    `_has_any_file` was the old test, so a dry report — a reading, not
    paperwork — ticked INITIAL PAPERWORK by itself.
    """
    if not folder or not os.path.isdir(folder):
        return False
    try:
        import audit_logic
        with os.scandir(folder) as it:
            return any(e.is_file() and audit_logic.is_initial_paperwork(e.name)
                       for e in it)
    except Exception:
        return False


def _has_any_file(folder: str) -> bool:
    if not folder or not os.path.isdir(folder):
        return False
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.is_file() and not e.name.startswith("."):
                    return True
    except OSError:
        return False
    return False


def _has_any_image(folder: str, *, budget_seconds: float = 5.0) -> bool:
    """Return True iff `folder` contains at least one image (recursive).

    OneDrive / SharePoint synced folders can take seconds to enumerate on
    a cold cache or during a sync hiccup; this used to freeze the audit
    UI thread indefinitely. `budget_seconds` caps the walk — once
    exceeded we return False (interpreted downstream as "missing
    photos", which is the safe wrong answer) and log so the pattern is
    visible in ems.log. Doesn't protect against a single blocking
    scandir() syscall — that requires threading; this is the cheap
    common-case fix.
    """
    if not folder or not os.path.isdir(folder):
        return False
    import time as _t
    deadline = _t.monotonic() + budget_seconds
    try:
        for root, _dirs, files in os.walk(folder):
            if _t.monotonic() > deadline:
                try:
                    import ems_log
                    ems_log.warn("process_card_dialog",
                                  f"_has_any_image budget exceeded "
                                  f"({budget_seconds}s) for {folder!r}")
                except Exception:
                    pass
                return False
            for f in files:
                if f.startswith("."):
                    continue
                if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                    return True
    except OSError:
        return False
    return False


def _has_docusketch_folder(job_path: str) -> bool:
    if not job_path or not os.path.isdir(job_path):
        return False
    for candidate in (
        os.path.join(job_path, "EMS", "DOCS", "Docusketch"),
        os.path.join(job_path, "EMS", "Docusketch"),
        os.path.join(job_path, "Docusketch"),
    ):
        if os.path.isdir(candidate):
            return True
    return False


def _has_scope_pdf(job_path: str) -> bool:
    if not job_path or not os.path.isdir(job_path):
        return False
    for candidate in (
        os.path.join(job_path, "EMS", "DOCS", "Scope.pdf"),
        os.path.join(job_path, "DOCS", "Scope.pdf"),
        os.path.join(job_path, "Scope.pdf"),
    ):
        if os.path.isfile(candidate):
            return True
    return False


def _missing_ems_subs(job_path: str) -> list[str]:
    """Returns the EMS subfolders that are missing on disk, in the
    order the scaffolder will create them."""
    if not job_path or not os.path.isdir(job_path):
        return []
    out: list[str] = []
    for rel in ("EMS", os.path.join("EMS", "DOCS"),
                 os.path.join("EMS", "PICS")):
        full = os.path.join(job_path, rel)
        if not os.path.isdir(full):
            out.append(rel)
    return out


def _detect_state(job_path: str, sp_new_count: int = 0) -> dict:
    """Snapshot of what's on disk vs not, used to seed dialog defaults
    and label rows in the preview. Cheap — bounded directory walks.

    `sp_new_count` is passed in by the caller (the IUQ row knows it
    from the cached audit payload) so we don't have to re-run a SP
    folder scan inside the dialog."""
    pics_initial = os.path.join(job_path, "EMS", "PICS", "Initial")
    docs = os.path.join(job_path, "EMS", "DOCS")
    return {
        "missing_folders": _missing_ems_subs(job_path),
        "has_initial_photos": _has_any_image(pics_initial),
        # An intake FORM, not merely "a file in DOCS" — a dry report is
        # a reading and used to tick INITIAL PAPERWORK on its own.
        "has_initial_docs":   _has_initial_forms(docs),
        "has_docusketch":     _has_docusketch_folder(job_path),
        "has_scope":          _has_scope_pdf(job_path),
        "sp_new":             int(sp_new_count or 0),
    }


def open_process_dialog(parent, *, card: dict, audit_app=None,
                        on_done=None) -> None:
    """Pop the Process Card modal.

    `card` must contain at least: card_id, client, job_path.
    `audit_app` is the RunAuditApp (when available) so the SP-import
    step can hand off to its `audit_single_client(..., then_open_sp=
    True)` flow. Pass None to hide the SP step (the rest still works).
    `on_done(success: bool)` fires after the dialog closes with
    success=True iff the user actually clicked Process and the
    confirmation comment posted.
    """
    client = (card.get("client") or "").strip()
    card_id = (card.get("card_id") or card.get("id") or "").strip()
    job_path = (card.get("job_path") or "").strip()
    sp_new = int(card.get("sharepoint_new") or 0)

    if not client or not card_id:
        messagebox.showerror(
            "Can't process",
            "This row is missing either the client name or the "
            "Trello card_id — re-pin via 📌 and try again.",
            parent=parent)
        return

    state = _detect_state(job_path, sp_new_count=sp_new)

    dlg = tk.Toplevel(parent)
    dlg.title("⚡ Process card")
    dlg.configure(bg=BG)
    dlg.transient(parent.winfo_toplevel())
    dlg.withdraw()
    dlg.grab_set()
    try:
        dlg.geometry("520x620")
    except tk.TclError:
        pass

    # ── Header ────────────────────────────────────────────────────
    hdr = tk.Frame(dlg, bg=BG, padx=18, pady=14)
    hdr.pack(fill="x")
    tk.Label(hdr, text="⚡ Process card",
             font=("Fraunces", 16, "bold"),
             bg=BG, fg=TEXT_DARK, anchor="w"
             ).pack(fill="x")
    tk.Label(hdr, text=client,
             font=("Segoe UI Variable", 11),
             bg=BG, fg=TEXT_GRAY, anchor="w"
             ).pack(fill="x", pady=(2, 0))
    tk.Label(hdr,
             text=("Chain the end-of-intake steps. Defaults are "
                   "based on what's on disk; uncheck anything you "
                   "want to skip."),
             font=("Segoe UI Variable", 9),
             bg=BG, fg=TEXT_GRAY,
             wraplength=470, justify="left", anchor="w"
             ).pack(fill="x", pady=(4, 0))

    # ── Detection summary ─────────────────────────────────────────
    body = tk.Frame(dlg, bg=WHITE, padx=18, pady=14)
    body.pack(fill="both", expand=True, padx=14, pady=(0, 8))

    tk.Label(body, text="On disk",
             font=("Segoe UI Variable", 10, "bold"),
             bg=WHITE, fg=TEXT_DARK, anchor="w"
             ).pack(fill="x", pady=(0, 4))

    def _status_row(label, present: bool, detail: str = ""):
        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=1)
        icon = "✅" if present else "⚠"
        icon_fg = SUCCESS_FG if present else WARN_FG
        tk.Label(row, text=icon, font=("Segoe UI Emoji", 10),
                 bg=WHITE, fg=icon_fg).pack(side="left")
        tk.Label(row, text=f"  {label}",
                 font=("Segoe UI Variable", 9),
                 bg=WHITE, fg=TEXT_DARK, anchor="w"
                 ).pack(side="left")
        if detail:
            tk.Label(row, text=f"  · {detail}",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, anchor="w"
                     ).pack(side="left")

    _status_row("EMS folder structure",
                not state["missing_folders"],
                detail=("missing " + ", ".join(state["missing_folders"])
                        if state["missing_folders"]
                        else "EMS / DOCS / PICS all present"))
    _status_row("Initial paperwork in EMS/DOCS",
                state["has_initial_docs"])
    _status_row("Initial photos in PICS/Initial",
                state["has_initial_photos"])
    _status_row("Sketch (Docusketch folder)",
                state["has_docusketch"])
    _status_row("Scope.pdf",
                state["has_scope"])
    if audit_app is not None:
        _status_row(f"SP photos waiting (+{state['sp_new']} new)",
                    state["sp_new"] == 0)

    # ── Actions checklist ────────────────────────────────────────
    tk.Frame(body, bg=BORDER, height=1
              ).pack(fill="x", pady=(10, 8))

    tk.Label(body, text="Actions",
             font=("Segoe UI Variable", 10, "bold"),
             bg=WHITE, fg=TEXT_DARK, anchor="w"
             ).pack(fill="x", pady=(0, 4))

    # Each action: (key, label, default-checked, only-show-if-cond).
    actions: list[tuple[str, str, bool, bool]] = []
    actions.append((
        "make_folders",
        "Create missing EMS folders",
        bool(state["missing_folders"]),
        bool(state["missing_folders"]),
    ))
    if audit_app is not None:
        actions.append((
            "import_sp",
            f"Import {state['sp_new']} SP photo(s) into PICS/Initial",
            state["sp_new"] > 0,
            state["sp_new"] > 0,
        ))
    actions.append((
        "tick_present",
        "Tick Trello checklist items for everything on disk",
        True,
        True,
    ))
    actions.append((
        "post_comment",
        f"Post '{_CANONICAL_COMMENT}' comment on Trello",
        True,
        True,
    ))
    actions.append((
        "tick_initial_upload",
        "Tick the INITIAL UPLOAD checklist item (closes the card here)",
        True,
        True,
    ))

    action_vars: dict[str, tk.BooleanVar] = {}
    for key, label, default, visible in actions:
        if not visible:
            continue
        v = tk.BooleanVar(value=bool(default))
        action_vars[key] = v
        cb = tk.Checkbutton(
            body, text=label, variable=v,
            font=("Segoe UI Variable", 10),
            bg=WHITE, fg=TEXT_DARK,
            activebackground=WHITE,
            selectcolor=SURFACE_2,
            anchor="w", padx=2, pady=2)
        cb.pack(fill="x", padx=(8, 0))

    # ── Footer ───────────────────────────────────────────────────
    bot = tk.Frame(dlg, bg=BG, padx=18, pady=12)
    bot.pack(fill="x", side="bottom")

    result_holder = [False]

    def _cancel():
        result_holder[0] = False
        dlg.destroy()

    def _process():
        # Capture user-selected actions and run them in order.
        run_make = action_vars.get("make_folders")
        run_sp = action_vars.get("import_sp")
        run_tick = action_vars.get("tick_present")
        run_post = action_vars.get("post_comment")
        run_close = action_vars.get("tick_initial_upload")

        # 1. Scaffold missing EMS folders.
        if run_make is not None and run_make.get() and job_path:
            for rel in state["missing_folders"]:
                try:
                    os.makedirs(os.path.join(job_path, rel),
                                exist_ok=True)
                except OSError:
                    pass

        # 2. Hand off to the audit panel's SP-import flow.
        if run_sp is not None and run_sp.get() and audit_app is not None:
            try:
                audit_app.audit_single_client(
                    client, then_open_sp=True)
            except Exception:
                pass

        # 3. Auto-tick the on-disk items.
        ticked: list[tuple[str, str]] = []
        if run_tick is not None and run_tick.get() and card_id:
            events: list[str] = []
            # Re-detect (folders might have been scaffolded above; SP
            # import happens in the background so its results aren't
            # visible yet — we only tick what's ALREADY on disk).
            fresh = _detect_state(job_path)
            if fresh["has_initial_docs"]:
                events.append("initial_paperwork")
            if fresh["has_initial_photos"]:
                events.append("sp_photos_initial")
            if fresh["has_docusketch"]:
                events.append("docusketch_imported")
            if fresh["has_scope"]:
                events.append("scope_saved")
            if events:
                try:
                    import trello_autotick as _at
                    ticked = _at.autotick(card_id,
                                           events=tuple(events),
                                           client=client) or []
                except Exception:
                    ticked = []

        # 4. Post the canonical confirmation comment.
        comment_ok = False
        if run_post is not None and run_post.get() and card_id:
            try:
                import trello_client as tc
                tc.post_comment(card_id, _CANONICAL_COMMENT)
                comment_ok = True
            except Exception:
                comment_ok = False

        # 5. Tick INITIAL UPLOAD — this is the gate that drops the
        # card off the IUQ. Distinct from the on-disk autotick block
        # because INITIAL UPLOAD doesn't have a file on disk to
        # detect — the user's confirmation IS the artifact.
        close_ok = False
        if run_close is not None and run_close.get() and card_id:
            try:
                import trello_autotick as _at
                closed = _at.autotick(
                    card_id, events=("initial_upload_submitted",),
                    client=client)
                close_ok = bool(closed)
                ticked.extend(closed or [])
            except Exception:
                close_ok = False

        # Surface a single toast summarising what happened.
        try:
            from tool_panel import show_toast
            bits: list[str] = []
            if run_make is not None and run_make.get() and state["missing_folders"]:
                bits.append(f"folders: {len(state['missing_folders'])} created")
            if run_sp is not None and run_sp.get():
                bits.append("SP import opened")
            if ticked:
                bits.append(f"ticked {len(ticked)} Trello item(s)")
            if comment_ok:
                bits.append("posted confirmation")
            if bits:
                show_toast(parent, "⚡ Processed " + client + " — "
                            + ", ".join(bits),
                            kind="success", duration=4500)
            else:
                show_toast(parent,
                            "Nothing to do — every step was unchecked",
                            kind="info", duration=2500)
        except Exception:
            pass

        result_holder[0] = bool(comment_ok or close_ok or ticked)
        dlg.destroy()

    secondary_button(bot, "Cancel", command=_cancel
                      ).pack(side="right", padx=(6, 0))
    done_button(bot, "⚡ Process",
                 command=_process).pack(side="right")

    # Center + show
    try:
        dlg.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() // 2)
        py = parent.winfo_rooty() + (parent.winfo_height() // 2)
        dw = dlg.winfo_width()
        dh = dlg.winfo_height()
        dlg.geometry(f"+{px - dw // 2}+{py - dh // 2}")
        dlg.deiconify()
    except tk.TclError:
        pass
    dlg.wait_window()

    if on_done:
        try:
            on_done(bool(result_holder[0]))
        except Exception:
            pass
