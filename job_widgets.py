"""Client-card UI helpers shared across audit-style tools.

These widgets render the same per-client chrome — saved-memory pin badges,
right-click memory-clear menus, the standard folder picker — that the run
audit, audit backlog, snapshot audit view, and start-day panel all need.

Centralizing keeps the look consistent and prevents bug fixes (like the
"wrong folder auto-grabbed" override) from being applied unevenly across
tools that copy-paste their card rendering.
"""
import os
import re
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import persistence
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    BORDER, FLAG_RED, NEUTRAL_HOVER,
                    SUCCESS_BG, SUCCESS_FG)
from tool_panel import show_toast, ScrollableFrame
from ui_buttons import done_button, secondary_button


def prompt_audit_folder_override(parent, *, prompt_for_name=False,
                                  insured=None, initial_dir=None,
                                  title="Audit folder",
                                  intro=None):
    """Modal dialog: optional insured field + folder picker.

    Two callers share this UI today:
      * Run Audit's "🔍 Audit One Job" needs both the insured name AND
        an optional folder override — pass prompt_for_name=True.
      * Snapshot's "Audit Only" already has the insured typed into its
        own form, so it just needs the folder picker — pass
        prompt_for_name=False and insured="<typed name>" so the dialog
        title/banner reads correctly.

    Returns:
      * (name, folder)        when prompt_for_name=True (folder may be "")
      * folder_or_empty_str   when prompt_for_name=False
      * None                  when the user cancels
    """
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=BG)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("520x240" if prompt_for_name else "520x220")
    state = {"name": None, "folder": None, "cancelled": True}

    if prompt_for_name:
        tk.Label(dlg, text="Insured / job name:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK
                 ).pack(anchor="w", padx=14, pady=(12, 2))
        name_var = tk.StringVar(value=(insured or ""))
        ent = tk.Entry(dlg, textvariable=name_var,
                       font=("Segoe UI Variable", 10), bg=WHITE,
                       relief="solid", bd=1)
        ent.pack(fill="x", padx=14)
        ent.focus_set()
    else:
        name_var = None
        ent = None
        if insured:
            tk.Label(dlg, text=f"Auditing: {insured}",
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=BG, fg=TEXT_DARK
                     ).pack(anchor="w", padx=14, pady=(12, 4))

    if intro:
        tk.Label(dlg, text=intro,
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY,
                 wraplength=480, justify="left"
                 ).pack(anchor="w", padx=14, pady=(0, 4))

    tk.Label(dlg, text="Folder override (optional):",
             font=("Segoe UI Variable", 9, "bold"),
             bg=BG, fg=TEXT_DARK
             ).pack(anchor="w", padx=14, pady=(8, 2))
    folder_var = tk.StringVar(value="(use auto-match)")
    folder_lbl = tk.Label(dlg, textvariable=folder_var,
                          font=("Consolas", 8), bg=BG, fg=TEXT_GRAY,
                          wraplength=480, justify="left", anchor="w")
    folder_lbl.pack(fill="x", padx=14)
    picked = {"path": None}
    row = tk.Frame(dlg, bg=BG)
    row.pack(fill="x", padx=14, pady=(6, 0))

    def _pick():
        start = initial_dir if initial_dir and os.path.isdir(initial_dir) \
            else os.path.expanduser("~")
        chosen = filedialog.askdirectory(
            parent=dlg, initialdir=start,
            title="Pick the exact job folder")
        if chosen:
            picked["path"] = chosen
            folder_var.set(chosen)
            folder_lbl.config(fg=GREEN_DARK)
            # Folder's basename IS the insured name on this share —
            # auto-fill so the user doesn't have to retype it. Only
            # touch the field when it's blank; if they typed something
            # already, respect it.
            if name_var is not None and not (name_var.get() or "").strip():
                name_var.set(os.path.basename(chosen.rstrip("/\\")))

    def _clear():
        picked["path"] = None
        folder_var.set("(use auto-match)")
        folder_lbl.config(fg=TEXT_GRAY)

    secondary_button(row, "Pick folder…", padx=8, pady=2,
                      font=("Segoe UI Variable", 8),
                      command=_pick).pack(side="left")
    secondary_button(row, "Clear", padx=8, pady=2,
                      font=("Segoe UI Variable", 8),
                      command=_clear).pack(side="left", padx=(6, 0))

    btn_row = tk.Frame(dlg, bg=BG)
    btn_row.pack(side="bottom", fill="x", pady=(0, 12))

    def _ok():
        if prompt_for_name:
            n = (name_var.get() or "").strip()
            # When a folder was picked, the basename IS the insured —
            # we don't need a typed name to find anything. Only error
            # if BOTH fields are empty (no name + no folder = nothing
            # to audit).
            if not n:
                if picked["path"]:
                    n = os.path.basename(picked["path"].rstrip("/\\"))
                else:
                    messagebox.showerror(
                        "Need a name or a folder",
                        "Enter an insured/job name, or pick the job "
                        "folder directly.",
                        parent=dlg)
                    return
            state["name"] = n
        state["folder"]    = picked["path"] or ""
        state["cancelled"] = False
        dlg.destroy()

    def _cancel():
        state["cancelled"] = True
        dlg.destroy()

    secondary_button(btn_row, "Cancel", padx=14, pady=4,
                      command=_cancel).pack(side="right", padx=(4, 14))
    done_button(btn_row, "Audit", padx=14, pady=4,
                 command=_ok).pack(side="right", padx=4)
    if ent is not None:
        ent.bind("<Return>", lambda e: _ok())
    dlg.bind("<Return>", lambda e: _ok())
    dlg.bind("<Escape>", lambda e: _cancel())
    dlg.wait_window()

    if state["cancelled"]:
        return None
    if prompt_for_name:
        return (state["name"], state["folder"] or None)
    return state["folder"]


def extract_job_year(path):
    """Pull the 4-digit year out of `<root>/<YEAR Jobs>/<client>` style
    paths. Falls back to today's year when the path doesn't contain one
    (or path is None).

    Audit job paths look like ``X:\\IE_Public\\2026 Jobs\\Smith, John\\``,
    so the year sits in the basename of the parent. Notes/forms storage
    keys off this year, so getting it right matters per-job.
    """
    if not path:
        return datetime.today().year
    try:
        parent = os.path.basename(os.path.dirname(path))
    except Exception:
        return datetime.today().year
    m = re.search(r'(\d{4})', parent)
    if m:
        return int(m.group(1))
    return datetime.today().year


def render_memory_pin(parent, client, path=None, bg=None,
                      fg=None, font=("Segoe UI Variable", 8)):
    """Render the 📁/C/🗒 saved-memory strip for a client and pack it.

    Indicators (in order):
      📁  saved folder-path override exists
      C   marked Commercial
      🗒  has a job note

    Returns the packed Label, or None when no memory is set (caller can
    skip layout adjustments). `bg` / `fg` default to live theme values
    so the strip picks up dark mode without callers updating.
    """
    if bg is None:
        bg = WHITE
    if fg is None:
        fg = GREEN_DARK
    has_path = persistence.get_folder_path(client) is not None
    has_comm = persistence.is_commercial(client)
    year     = extract_job_year(path)
    # Lazy import — job_notes_gui pulls in tk + parsing deps; not every
    # caller of this module needs it loaded.
    try:
        from job_notes_gui import has_note as _jn_has_note
    except Exception:
        _jn_has_note = lambda *_: False
    has_note = persistence.has_note(client) or _jn_has_note(year, client)

    if not (has_path or has_comm or has_note):
        return None
    bits = []
    if has_path: bits.append("📁")
    if has_comm: bits.append("C")
    if has_note: bits.append("🗒")
    lbl = tk.Label(parent, text="".join(bits), font=font, bg=bg, fg=fg)
    lbl.pack(side="left", padx=(2, 0))
    return lbl


def pick_job_folder(parent, client, initial=None, audit_base=None):
    """Standard folder picker — used both for "find folder" (when auto-detect
    failed) and for "change folder" (when auto-detect picked the wrong one).

    Returns the picked path string, or None if the user cancelled.
    """
    init = initial
    if not init or not os.path.isdir(init):
        init = audit_base if (audit_base and os.path.isdir(audit_base)) \
               else os.path.expanduser("~")
    return filedialog.askdirectory(
        title=f"Select folder for: {client}",
        initialdir=init,
        parent=parent) or None


def open_trello_pin_dialog(parent, client, *, on_pinned=None):
    """Multi-select Trello card picker for `client`.

    Used by Job Notes' "📌 Pin to Trello…" toolbar button, the audit
    card's inline pin button, and the right-click "Pin to Trello…" menu
    item — every entry point into pinning routes through this one
    dialog so the picker UX stays identical everywhere.

    Pre-checks any cards already pinned for the client. Includes a
    "Paste Trello URL" field for cards fuzzy search misses (manually-
    pasted ids are validated by fetching the card before save).

    On Save: persists via `persistence.set_trello_card_ids(client, ids)`,
    then calls `on_pinned(card_ids)` if provided. On Cancel: no-op."""
    if not client:
        return
    try:
        import trello_client
    except Exception as ex:
        messagebox.showerror("Trello unavailable",
                             f"Couldn't load trello_client:\n{ex}",
                             parent=parent)
        return
    try:
        matches = trello_client.find_cards_by_name(client, max_results=12)
    except Exception as ex:
        # Surface auth/network issue but still open the picker so the
        # user can paste a URL manually.
        show_toast(parent, f"Trello search failed: {ex}", kind="error")
        matches = []

    prechecked = set(persistence.get_trello_card_ids(client))

    dlg = tk.Toplevel(parent)
    dlg.title(f"Link {client} to Trello")
    dlg.configure(bg=BG)
    dlg.transient(parent)
    dlg.grab_set()

    # Header
    tk.Label(dlg,
             text=f"Link '{client}' to Trello card(s)",
             font=("Segoe UI Variable", 11, "bold"),
             bg=BG, fg=TEXT_DARK,
             padx=14).pack(anchor="w", pady=(12, 2))
    tk.Label(dlg,
             text=("Check every card that represents this job — same job "
                   "sometimes lives on 2+ boards (e.g. WIP + AR). Each "
                   "linked card gets its own tab in Job Notes."),
             font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
             padx=14, wraplength=540, justify="left"
             ).pack(anchor="w", pady=(0, 8))

    list_card = tk.Frame(dlg, bg=WHITE,
                         highlightthickness=1, highlightbackground=BORDER)
    list_card.pack(fill="both", expand=True, padx=14, pady=(0, 10))
    if matches:
        tk.Label(list_card, text="Fuzzy-match results",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=SUCCESS_BG, fg=SUCCESS_FG,
                 padx=10, pady=4, anchor="w").pack(fill="x")
        scroll_holder = tk.Frame(list_card, bg=WHITE)
        scroll_holder.pack(fill="both", expand=True)
        inner = ScrollableFrame(scroll_holder, bg=WHITE, height=240)
        inner.pack(fill="both", expand=True)
        inner_box = inner.inner
    else:
        tk.Label(list_card,
                 text=("No fuzzy matches. Paste a Trello card URL below "
                       "to link manually."),
                 font=("Segoe UI Variable", 9, "italic"),
                 bg=WHITE, fg=TEXT_GRAY,
                 padx=12, pady=10, anchor="w").pack(fill="x")
        inner_box = None

    check_vars = []  # list of (card_id, BooleanVar)
    if inner_box is not None:
        for m in matches:
            cid = m.get("card_id")
            if not cid:
                continue
            var = tk.BooleanVar(value=(cid in prechecked))
            check_vars.append((cid, var))
            row = tk.Frame(inner_box, bg=WHITE, padx=10, pady=4)
            row.pack(fill="x")
            tk.Checkbutton(row, variable=var, bg=WHITE,
                           activebackground=WHITE, selectcolor=WHITE
                           ).pack(side="left")
            txt = tk.Frame(row, bg=WHITE)
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=m.get("name", "?"),
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=TEXT_DARK,
                     anchor="w").pack(fill="x")
            sub_bits = [m.get("board", "?")]
            if m.get("list_name"):
                sub_bits.append(m["list_name"])
            tk.Label(txt, text="  ·  ".join(sub_bits),
                     font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY,
                     anchor="w").pack(fill="x")
            def _toggle(_e=None, v=var):
                v.set(not v.get())
            row.bind("<Button-1>", _toggle)
            txt.bind("<Button-1>", _toggle)
            for child in txt.winfo_children():
                child.bind("<Button-1>", _toggle)
            tk.Frame(inner_box, bg=BORDER, height=1).pack(fill="x")

    # Manual paste field
    manual_frame = tk.Frame(dlg, bg=BG, padx=14)
    manual_frame.pack(fill="x", pady=(0, 8))
    tk.Label(manual_frame, text="Or paste a Trello card URL or short id:",
             font=("Segoe UI Variable", 9, "bold"),
             bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
    tk.Label(manual_frame,
             text="Examples: https://trello.com/c/abc12345/job-name "
                  "—  abc12345  —  full 24-char card id",
             font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
             anchor="w").pack(fill="x")
    manual_var = tk.StringVar()
    ttk.Entry(manual_frame, textvariable=manual_var,
              font=("Segoe UI Variable", 9), width=60).pack(fill="x", pady=(2, 0))
    manual_status = tk.Label(manual_frame, text="",
                              font=("Segoe UI Variable", 8),
                              bg=BG, fg=TEXT_GRAY, anchor="w")
    manual_status.pack(fill="x")
    def _validate_manual(*_a):
        raw = manual_var.get().strip()
        if not raw:
            manual_status.config(text="", fg=TEXT_GRAY)
            return
        cid = trello_client.parse_card_identifier(raw)
        if cid:
            manual_status.config(text=f"✓ recognized as card '{cid}'",
                                 fg=SUCCESS_FG)
        else:
            manual_status.config(
                text="⚠ doesn't look like a Trello URL or short id",
                fg=FLAG_RED)
    manual_var.trace_add("write", _validate_manual)

    def _do_save():
        ids = [cid for cid, var in check_vars if var.get()]
        raw = manual_var.get().strip()
        if raw:
            manual_id = trello_client.parse_card_identifier(raw)
            if not manual_id:
                messagebox.showerror(
                    "Invalid Trello link",
                    "The pasted text doesn't look like a Trello card URL "
                    "or short id. Cards have URLs like:\n\n"
                    "  https://trello.com/c/abc12345/some-name\n\n"
                    "Either copy that URL from Trello, or just paste the "
                    "8-character code that follows /c/.",
                    parent=dlg)
                return
            try:
                card = trello_client.get_card(manual_id)
            except Exception as ex:
                messagebox.showerror(
                    "Trello fetch failed",
                    f"Couldn't reach Trello to verify the pasted card:"
                    f"\n\n{ex}",
                    parent=dlg)
                return
            if not card:
                messagebox.showerror(
                    "Card not found",
                    f"Trello returned no card for '{manual_id}'. "
                    "Either the link is wrong, or the card lives in a "
                    "board your account can't access.",
                    parent=dlg)
                return
            if manual_id not in ids:
                ids.append(manual_id)
        persistence.set_trello_card_ids(client, ids)
        dlg.destroy()
        if ids:
            show_toast(parent,
                       f"Linked {client} to {len(ids)} Trello "
                       f"card{'s' if len(ids) != 1 else ''}", kind="info")
        else:
            show_toast(parent,
                       f"Unlinked {client} from Trello", kind="info")
        if on_pinned is not None:
            try:
                on_pinned(ids)
            except Exception:
                pass

    bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
    bot.pack(fill="x")
    secondary_button(bot, "Cancel", padx=14, pady=4,
                      command=dlg.destroy
                      ).pack(side="right", padx=(8, 0))
    done_button(bot, "Save", padx=18, pady=4,
                 command=_do_save).pack(side="right")

    dlg.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w = max(dlg.winfo_reqwidth(), 580)
        h = max(dlg.winfo_reqheight(), 480)
        dlg.geometry(f"{w}x{h}+{px + (pw-w)//2}+{py + (ph-h)//3}")
    except Exception:
        pass


def open_search_aliases_dialog(parent, client, *, on_save=None):
    """Modal dialog for editing the per-client search alias list.

    Aliases are alternate names every name-based lookup (SP folder scan,
    audit folder lookup, Trello card fuzzy match) should also try when
    searching for this client. Stored via
    `persistence.get/set_search_aliases`.

    `on_save(aliases)` fires after a successful Save (use this to
    re-render the audit row, refresh the SP scan, etc.). Cancel does
    nothing — never modifies state.
    """
    aliases = persistence.get_search_aliases(client)
    dlg = tk.Toplevel(parent)
    dlg.title(f"Search aliases — {client}")
    dlg.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel")
                   else parent)
    dlg.resizable(True, True)
    dlg.configure(bg=WHITE)

    body = tk.Frame(dlg, bg=WHITE, padx=18, pady=14)
    body.pack(fill="both", expand=True)
    tk.Label(body, text=f"Other names to also search for '{client}':",
             font=("Segoe UI Variable", 10, "bold"),
             bg=WHITE, fg=TEXT_DARK).pack(anchor="w")
    tk.Label(body,
             text=("One alias per line. These names get tried by SP "
                   "folder scan, the audit folder lookup, and the Trello "
                   "card matcher whenever the canonical name above is "
                   "searched."),
             font=("Segoe UI Variable", 8), fg=TEXT_GRAY,
             bg=WHITE, wraplength=420, justify="left"
             ).pack(anchor="w", pady=(2, 8))
    txt = tk.Text(body, height=8, width=48,
                   font=("Segoe UI Variable", 10),
                   bg=WHITE, fg=TEXT_DARK,
                   insertbackground=TEXT_DARK,
                   relief="solid", bd=1, wrap="word")
    txt.pack(fill="both", expand=True)
    if aliases:
        txt.insert("1.0", "\n".join(aliases))

    btn_row = tk.Frame(body, bg=WHITE)
    btn_row.pack(fill="x", pady=(10, 0))

    def _save():
        raw = txt.get("1.0", "end").strip()
        new_aliases = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        persistence.set_search_aliases(client, new_aliases)
        try:
            if on_save:
                on_save(new_aliases)
        except Exception:
            pass
        dlg.destroy()

    secondary_button(btn_row, "Cancel", padx=12, pady=4,
                      command=dlg.destroy).pack(side="right")
    done_button(btn_row, "Save", padx=14, pady=4,
                 command=_save).pack(side="right", padx=(0, 6))

    dlg.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w = max(dlg.winfo_reqwidth(), 460)
        h = max(dlg.winfo_reqheight(), 280)
        dlg.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 3}")
    except Exception:
        pass
    txt.focus_set()
    dlg.grab_set()


def _new_property_with_folder(host, folder_basename):
    """Mini-dialog: prompt for a property name + create the group
    pre-seeded with this folder. Quicker than opening the Multi-Unit
    panel just to add one unit — keeps the audit row's right-click
    flow self-contained."""
    dlg = tk.Toplevel(host)
    dlg.title("New property")
    dlg.transient(host.winfo_toplevel() if hasattr(host, "winfo_toplevel")
                   else host)
    dlg.grab_set()
    dlg.resizable(False, False)
    frm = tk.Frame(dlg, padx=20, pady=14)
    frm.pack()
    tk.Label(frm, text="Property name",
              font=("Segoe UI Variable", 9, "bold")).pack(anchor="w")
    tk.Label(frm, text=f"Will include this folder: {folder_basename}",
              font=("Segoe UI Variable", 8, "italic"), fg=TEXT_GRAY
              ).pack(anchor="w", pady=(0, 4))
    name_var = tk.StringVar()
    entry = ttk.Entry(frm, textvariable=name_var, width=40,
                       font=("Segoe UI Variable", 10))
    entry.pack(anchor="w", pady=(0, 10))
    entry.focus_set()
    def _save():
        n = name_var.get().strip()
        if not n:
            return
        persistence.set_property_group(n, [folder_basename])
        dlg.destroy()
        show_toast(host, f"Created '{n}' with 1 unit. Open Multi-Unit "
                          "to add more.", kind="info")
    btns = tk.Frame(frm)
    btns.pack(anchor="e")
    secondary_button(btns, "Cancel", padx=10, pady=4,
                      command=dlg.destroy
                      ).pack(side="left", padx=(0, 6))
    done_button(btns, "Create", padx=12, pady=4,
                 command=_save).pack(side="left")
    entry.bind("<Return>", lambda _e: _save())


# Admin checklists the EMS Admin works out of, in lifecycle order.
# Matched case-insensitively against the card's checklist names.
_ADMIN_CHECKLISTS = ("INITIAL - ADMIN", "IN PROGRESS - ADMIN",
                      "CLOSE OUT - ADMIN")


def open_checklist_ticker(host, client):
    """Pop a dialog showing the card's three admin checklists (Initial /
    In Progress / Close Out) with a checkbox per item, so the user can
    tick any item by hand — a "just in case" manual fallback for the
    audit's automatic ticking. Fetches the pinned card in a background
    thread; toggling an item writes straight back to Trello."""
    pinned = persistence.get_trello_card_ids(client) or []
    if not pinned:
        show_toast(host,
                   f"No Trello card pinned for {client} — pin one first.",
                   kind="info")
        return
    card_id = pinned[0]

    dlg = tk.Toplevel(host)
    dlg.title(f"Trello checklists — {client}")
    dlg.configure(bg=BG)
    dlg.geometry("440x520")
    try:
        dlg.transient(host.winfo_toplevel())
    except Exception:
        pass

    tk.Label(dlg, text=client, font=("Segoe UI Variable", 12, "bold"),
             bg=BG, fg=TEXT_DARK).pack(anchor="w", padx=16, pady=(12, 0))
    status = tk.Label(dlg, text="Loading checklists…",
                      font=("Segoe UI Variable", 9, "italic"),
                      bg=BG, fg=TEXT_GRAY)
    status.pack(anchor="w", padx=16, pady=(2, 8))

    body = ScrollableFrame(dlg, bg=BG)
    body.pack(fill="both", expand=True, padx=8, pady=(0, 10))
    inner = body.inner

    def _toggle(item_id, var):
        new_state = "complete" if var.get() else "incomplete"

        def _bg():
            ok = False
            try:
                import trello_client as _tc
                ok = bool(_tc.set_check_item_state(
                    card_id, item_id, new_state))
            except Exception:
                ok = False

            def _done():
                if ok:
                    show_toast(dlg,
                               "Ticked ✓" if new_state == "complete"
                               else "Un-ticked", kind="success")
                else:
                    var.set(not var.get())  # revert
                    show_toast(dlg, "Trello update failed", kind="error")
            try:
                dlg.after(0, _done)
            except tk.TclError:
                pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def _render(card):
        for w in inner.winfo_children():
            try: w.destroy()
            except tk.TclError: pass
        if not card:
            status.config(text="Couldn't load the card.")
            return
        checklists = card.get("checklists") or []
        by_name = {(cl.get("name") or "").strip().lower(): cl
                   for cl in checklists}
        shown = 0
        for name in _ADMIN_CHECKLISTS:
            cl = by_name.get(name.lower())
            if not cl:
                continue
            shown += 1
            tk.Label(inner, text=name,
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=BG, fg=GREEN_DARK).pack(anchor="w",
                                                 padx=8, pady=(10, 2))
            for item in (cl.get("checkItems") or []):
                done = (item.get("state") or "").lower() == "complete"
                var = tk.BooleanVar(value=done)
                cb = tk.Checkbutton(
                    inner, text=item.get("name") or "?",
                    variable=var, bg=BG, fg=TEXT_DARK,
                    activebackground=BG, anchor="w",
                    font=("Segoe UI Variable", 9),
                    command=lambda i=item.get("id"), v=var: _toggle(i, v))
                cb.pack(anchor="w", padx=18, fill="x")
        if shown:
            status.config(text="Tick an item to mark it done on Trello.")
        else:
            status.config(
                text="No Initial / In Progress / Close Out checklists "
                     "on this card.")

    def _fetch():
        card = None
        try:
            import trello_client as _tc
            card = _tc.get_card(card_id, actions_limit=0)
        except Exception:
            card = None
        try:
            dlg.after(0, lambda: _render(card))
        except tk.TclError:
            pass
    import threading
    threading.Thread(target=_fetch, daemon=True).start()

    tk.Button(dlg, text="Close", command=dlg.destroy,
              font=("Segoe UI Variable", 9), padx=12, pady=4
              ).pack(side="bottom", pady=(0, 10))


def show_card_context_menu_at_event(event, host, client, *,
                                      run_date=None,
                                      audit_base=None,
                                      on_change_folder=None,
                                      on_change_aliases=None):
    """Pop the shared client-card context menu at the event's coords.

    Same menu items as `attach_card_context_menu`'s permanent binding —
    Pin to Trello, Open Trello card, Change folder, Edit aliases,
    Property-group add/remove, Reset memory. Use this when the client
    name is dynamic (e.g. APA Monitor rows where the user types
    inline, so the client must be resolved at click time, not at bind
    time). When `client` is stable, use `attach_card_context_menu`
    instead — that variant handles the recursive child-tag walk so the
    right-click reaches all descendants of the card.
    """
    if not client:
        return
    def _change_folder():
        cur = persistence.get_folder_path(client)
        path = pick_job_folder(host, client, initial=cur,
                                audit_base=audit_base)
        if path is None:
            return
        persistence.set_folder_path(client, path)
        if on_change_folder is not None:
            try:
                on_change_folder(path)
            except Exception:
                pass
        else:
            show_toast(host, f"Folder updated for {client}", kind="info")

    def _reset_memory():
        from tkinter import messagebox
        if not messagebox.askyesno(
                "Reset memory",
                f"Clear ALL saved memory for {client}?\n\n"
                "• Saved folder path\n"
                "• Commercial flag\n"
                "• Resolved-issue checkmarks for today\n\n"
                "This cannot be undone.",
                parent=host):
            return
        persistence.set_folder_path(client, None)
        persistence.set_commercial(client, False)
        if run_date:
            try:
                state    = persistence._load()
                resolved = state.get("resolved_issues", {})
                prefix   = f"{run_date}::{client}::"
                for k in list(resolved.keys()):
                    if k.startswith(prefix):
                        del resolved[k]
                state["resolved_issues"] = resolved
                persistence._save(state)
            except Exception:
                pass
        show_toast(host, f"All memory cleared for {client}", kind="info")

    def _open_trello():
        try:
            import trello_client
        except Exception:
            show_toast(host, "Trello client not available", kind="error")
            return
        try:
            ok = trello_client.open_card_for_client(client)
        except Exception as ex:
            show_toast(host, f"Trello error: {ex}", kind="error")
            return
        if not ok:
            show_toast(host, f"No Trello card found for {client}", kind="info")

    def _open_xactanalysis():
        """Lazy-fetch the pinned card and open its XactAnalysis link in
        the browser. Runs the network round-trip in a background thread
        so the menu click doesn't freeze the UI."""
        try:
            import trello_client as _tc
        except Exception:
            show_toast(host, "Trello client not available", kind="error")
            return
        pinned = persistence.get_trello_card_ids(client) or []
        if not pinned:
            show_toast(host,
                       f"No Trello card pinned for {client} — pin one to "
                       "unlock the XA link.", kind="info")
            return

        def _bg(card_id=pinned[0]):
            try:
                card = _tc.get_card(card_id, actions_limit=0)
            except Exception as ex:
                host.after(0, lambda e=ex: show_toast(
                    host, f"Trello fetch failed: {e}", kind="error"))
                return
            url = _tc.card_xa_link(card) if card else ""
            if not url:
                host.after(0, lambda: show_toast(
                    host,
                    "Card has no XactAnalysis link in its description.",
                    kind="info"))
                return
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception as ex:
                host.after(0, lambda e=ex: show_toast(
                    host, f"Couldn't open browser: {e}", kind="error"))
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    menu = tk.Menu(host, tearoff=0)
    has_path = persistence.get_folder_path(client) is not None
    has_comm = persistence.is_commercial(client)
    pinned_count = len(persistence.get_trello_card_ids(client))
    pin_label = (f"Pin to Trello… ({pinned_count} linked)"
                 if pinned_count else "Pin to Trello…")
    menu.add_command(label=pin_label,
                     command=lambda: open_trello_pin_dialog(host, client))
    menu.add_command(label="Open Trello card", command=_open_trello)
    menu.add_command(label="Open XactAnalysis link",
                     command=_open_xactanalysis)
    menu.add_command(label="✓ Trello checklist… (tick by hand)",
                     command=lambda: open_checklist_ticker(host, client))

    def _request_docusign():
        """Trigger the Docusign request flow for the first pinned card.
        Looks up the insured's email from the card desc; posts the
        appropriate templated comment (paperwork-sent vs need-email-from-
        Kimberly) and registers the entry in the Hygiene Docusign-pending
        section."""
        pinned = persistence.get_trello_card_ids(client) or []
        if not pinned:
            show_toast(host,
                       f"No Trello card pinned for {client} — pin one to "
                       "request Docusign.", kind="info")
            return
        try:
            import docusign_requests as _dsr
        except Exception:
            show_toast(host, "Docusign module not available", kind="error")
            return
        import threading

        def _bg(card_id=pinned[0]):
            entry = None
            err = None
            try:
                entry = _dsr.request(card_id, client_name=client)
            except Exception as ex:
                err = str(ex)

            def _done():
                if err or not entry:
                    show_toast(host,
                               f"Docusign request failed: {err or 'card lookup'}",
                               kind="error")
                    return
                if entry.get("state") == "pending_email":
                    show_toast(host,
                               f"Docusign — no email on card. Tagged "
                               f"{_dsr.KIMBERLY_HANDLE} to call.",
                               kind="info")
                else:
                    show_toast(host,
                               f"Docusign sent to {entry.get('email')}.",
                               kind="info")
            host.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()
    menu.add_command(label="📝 Request Docusign",
                     command=_request_docusign)
    menu.add_separator()
    menu.add_command(label="Change folder…", command=_change_folder)
    existing_aliases = persistence.get_search_aliases(client)
    alias_label = (f"Edit search aliases… ({len(existing_aliases)})"
                   if existing_aliases else "Edit search aliases…")
    menu.add_command(
        label=alias_label,
        command=lambda: open_search_aliases_dialog(
            host, client, on_save=on_change_aliases))
    menu.add_separator()
    try:
        saved_path = persistence.get_folder_path(client)
    except Exception:
        saved_path = None
    folder_basename = (os.path.basename(saved_path)
                        if saved_path else "")
    if folder_basename:
        current_prop = persistence.find_property_for_folder(folder_basename)
        if current_prop:
            menu.add_command(
                label=f"Remove from property '{current_prop}'",
                command=lambda fb=folder_basename, p=current_prop: (
                    persistence.remove_folder_from_property_group(p, fb),
                    show_toast(host, f"Removed from '{p}'", kind="info")))
        else:
            groups = persistence.get_property_groups() or {}
            if groups:
                add_menu = tk.Menu(menu, tearoff=0)
                for gname in sorted(groups.keys(), key=str.lower):
                    add_menu.add_command(
                        label=gname,
                        command=lambda fb=folder_basename, g=gname: (
                            persistence.add_folder_to_property_group(g, fb),
                            show_toast(host, f"Added to '{g}'", kind="info")))
                add_menu.add_separator()
                add_menu.add_command(
                    label="+ New property…",
                    command=lambda fb=folder_basename: (
                        _new_property_with_folder(host, fb)))
                menu.add_cascade(label="Add to property…", menu=add_menu)
            else:
                menu.add_command(
                    label="Add to property…",
                    command=lambda fb=folder_basename: (
                        _new_property_with_folder(host, fb)))
    menu.add_separator()
    if has_path:
        menu.add_command(
            label="Clear saved folder path",
            command=lambda: (persistence.set_folder_path(client, None),
                             show_toast(host,
                                        f"Cleared saved folder path for {client}",
                                        kind="info")))
    if has_comm:
        menu.add_command(
            label="Clear Commercial flag",
            command=lambda: (persistence.set_commercial(client, False),
                             show_toast(host,
                                        f"{client} no longer marked Commercial",
                                        kind="info")))
    if has_path or has_comm:
        menu.add_separator()
    menu.add_command(label=f"Reset all memory for {client}",
                     command=_reset_memory)
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def attach_card_context_menu(host, widgets, client, *,
                              run_date=None,
                              on_change_folder=None,
                              on_change_aliases=None,
                              audit_base=None):
    """Right-click menu on a client card.

    Args:
        host: panel/Toplevel — used as messagebox/toast parent.
        widgets: a single widget or iterable of widgets to bind to.
        client: client name string.
        run_date: ISO date for the current audit run, used by "Reset all
            memory" to clear today's resolved-issue checkmarks. None skips
            that step.
        on_change_folder: optional callback `(new_path: str) -> None` invoked
            after the user picks a new folder (persistence is always updated).
            Most callers pass `self._run_audit` to re-render the row.
        audit_base: optional default folder for the picker dialog.

    When the client name varies over the row's lifetime (APA Monitor's
    text-edited rows), use `show_card_context_menu_at_event` directly
    from your own <Button-3> binding instead.
    """
    # The menu-building + handlers live on the shared
    # `show_card_context_menu_at_event` so the dynamic-client path
    # (APA Monitor) and the static-client path (here) emit identical
    # menus from one source of truth.
    def _show_menu(event):
        show_card_context_menu_at_event(
            event, host, client,
            run_date=run_date,
            audit_base=audit_base,
            on_change_folder=on_change_folder,
            on_change_aliases=on_change_aliases)

    if not isinstance(widgets, (list, tuple)):
        widgets = [widgets]

    # Bindtag approach — without this, right-clicks on the card's child
    # Labels/Buttons (most of the visible area) never reach the card frame
    # because Tk delivers events to the topmost widget under the cursor.
    # Solution: each root gets its own unique bindtag, the menu handler is
    # bound to that TAG (not the widget), and every descendant gets the tag
    # appended to its bindtags. One binding total — re-walking on Configure
    # is cheap because the tag append is idempotent.
    attach_card_context_menu._counter = getattr(
        attach_card_context_menu, "_counter", 0) + 1

    for idx, root in enumerate(widgets):
        tag = f"_cardctx_{attach_card_context_menu._counter}_{idx}"
        try:
            root.bind_class(tag, "<Button-3>", _show_menu)
        except tk.TclError:
            continue

        def _attach_tag_subtree(w, _tag=tag):
            try:
                bt = w.bindtags()
                if _tag not in bt:
                    w.bindtags(bt + (_tag,))
            except tk.TclError:
                return
            for child in w.winfo_children():
                _attach_tag_subtree(child)

        _attach_tag_subtree(root)

        # `attach_card_context_menu` is typically called RIGHT AFTER the
        # card frame is created — before its children (badge, body,
        # labels, buttons) are packed. The initial walk above only sees
        # the empty card frame; without a follow-up walk, the children
        # never get the bindtag and right-click silently misses on most
        # of the visible row area. Schedule a few re-walks at staggered
        # delays so we catch both synchronous (after_idle) and
        # near-synchronous (50ms / 250ms) child packing without relying
        # on Configure events firing reliably.
        def _make_rewalk(r=root, walk=_attach_tag_subtree):
            # Accept an optional event arg so this handler is callable
            # either as a Tk bind callback (event passed) or via
            # after()/after_idle (no event). Keeps a single function
            # safe to schedule from either path without a wrapper.
            def _on(_e=None):
                try:
                    if r.winfo_exists():
                        walk(r)
                except tk.TclError:
                    pass
            return _on

        try:
            root.after_idle(_make_rewalk())
            root.after(50, _make_rewalk())
            root.after(250, _make_rewalk())
        except tk.TclError:
            pass

        # Re-walk on <Configure> (debounced) so children added after the
        # initial bind — e.g. when _find_folder rebuilds a card or the
        # virtualizer realizes a body — also inherit the tag. The tag
        # append is a no-op for widgets that already have it, so this
        # can't compound. Bound on the root AND scheduled to also catch
        # body-level Configures via descendant resize → root resize
        # bubbling-via-pack (which doesn't actually bubble, but the
        # staggered after()s above handle the initial fill).
        def _make_configure(r=root, walk=_attach_tag_subtree):
            pending = [None]
            # Optional event arg — Tk bind passes one, but if any path
            # ever schedules this via after() (e.g. a defensive resync
            # call from another module), we don't want a TypeError. The
            # log saw exactly this crash on 2026-05-19 with no obvious
            # code path scheduling it args-less — defending broadly.
            def _on(_e=None):
                try:
                    if not r.winfo_exists():
                        return
                except tk.TclError:
                    return
                if pending[0] is not None:
                    try: r.after_cancel(pending[0])
                    except Exception: pass
                try:
                    pending[0] = r.after(80, lambda: walk(r))
                except tk.TclError:
                    pending[0] = None
            return _on
        try:
            root.bind("<Configure>", _make_configure(), add="+")
        except tk.TclError:
            pass


# ── Commercial-toggle cascade ───────────────────────────────────────────────
# Run Audit, Snapshot, and Daily Photo Folders all render a per-job "Comm."
# checkbox that, when toggled, strikes through the per-client forms a
# commercial job doesn't need (Auth to Perform, COS, etc.). The cascade
# was duplicated three times with subtle drift; consolidating here means
# bug fixes (like the sticky-state auto-apply) only land once.

class CommercialToggle:
    """Per-job "Comm." checkbox + cascade target.

    Usage:
        ct = CommercialToggle(parent, client, persist=True)
        if has_commercial_items:
            ct.checkbutton.pack(side="right", padx=(0, 4))
        for item in items:
            ...build per-row var + toggle_fn...
            if is_commercial_form(item):
                ct.register(var, toggle_fn)
        ct.auto_apply_if_sticky()  # call AFTER all items are registered

    `persist=True` reads/writes `persistence.commercial[client]` so the
    flag is sticky across audits. Daily Photos uses persist=False because
    its "Comm." checkbox is session-only (the file-creation flow has no
    long-lived state to remember).
    """

    def __init__(self, parent, client, *, persist=True, **checkbutton_kwargs):
        self.client = client
        self.persist = persist
        self.toggles = []   # list of (var, toggle_fn) registered by caller
        initial = persistence.is_commercial(client) if persist else False
        self.var = tk.BooleanVar(value=initial)
        # Sensible defaults that match the existing call sites; caller can
        # override via **checkbutton_kwargs if their parent uses a different
        # background or font.
        defaults = {
            "text":             "Comm.",
            "variable":         self.var,
            "font":             ("Segoe UI Variable", 7),
            "bg":               "#FFFFFF",
            "activebackground": "#FFFFFF",
            "selectcolor":      "#FFFFFF",
            "command":          self._on_toggle,
        }
        defaults.update(checkbutton_kwargs)
        self.checkbutton = tk.Checkbutton(parent, **defaults)

    def register(self, var, toggle_fn, issue=None):
        """Add a (BooleanVar, fn, issue) tuple to the cascade. The fn is
        the same toggle callback used when the user clicks the per-item
        checkbox — wrapping the cascade through it keeps strike-through,
        persistence, and any side effects consistent.

        `issue` (the persist_key string for this item) is optional but
        should be passed so that unchecking commercial also clears the
        carry-forward history for these items, preventing the 7-day
        window from re-pre-checking forms the user deliberately unmarked.
        """
        self.toggles.append((var, toggle_fn, issue))

    def _on_toggle(self):
        if self.persist:
            persistence.set_commercial(self.client, self.var.get())
        unchecking = not self.var.get()
        for entry in self.toggles:
            v, fn = entry[0], entry[1]
            issue = entry[2] if len(entry) > 2 else None
            if self.var.get() != v.get():
                v.set(self.var.get())
                fn()
            # On uncheck: always clear carry-forward history for this item
            # even if its var was already False.  Without this, a form
            # resolved by a previous commercial-toggle session stays in the
            # 7-day carry-forward window and re-pre-checks itself on the
            # next audit render.
            if unchecking and issue:
                try:
                    persistence.clear_resolved_history(self.client, issue)
                except Exception:
                    pass

    def auto_apply_if_sticky(self):
        """Fire the cascade once if the checkbox loaded as True from sticky
        persistence. Without this the box reads "checked" on the next day's
        audit but the rows it should skip still render red — the master
        Checkbutton's command does NOT fire on init."""
        if not self.var.get():
            return
        for entry in self.toggles:
            v, fn = entry[0], entry[1]
            if not v.get():
                v.set(True)
                fn()
