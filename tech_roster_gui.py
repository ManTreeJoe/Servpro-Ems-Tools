"""
Tech Roster dialog — manage user-added tech names + initials.

Names entered here get merged into `audit_logic.TECH_PATTERN` so every
tool (snapshot, run audit, job notes, workcenter) recognizes them
without a code change. The hardcoded roster is read-only — only entries
the user added through this dialog are editable here.

Opened from the Settings dialog footer ("Manage Tech Roster…").
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox

import audit_logic
import ctk_helpers as ctkh
import paths
import persistence
from theme import GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY, BORDER


class TechRosterDialog(tk.Toplevel):
    def __init__(self, parent=None, on_save=None):
        super().__init__(parent) if parent else super().__init__()
        self.on_save = on_save
        self.saved   = False

        self.title("Tech Roster")
        self.configure(bg=BG)
        self.resizable(False, True)
        self.minsize(560, 480)

        ico = paths.resource("wrench.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        # Load current state. Hardcoded names come straight from
        # audit_logic so this dialog reflects what the regex actually
        # uses, regardless of how the file evolves.
        self._user = persistence.get_user_techs()
        self._user_names = list(self._user.get("names", []))
        self._user_abbrev = dict(self._user.get("abbrev", {}))

        self._build_ui()
        self._render_user_list()
        self._center()

        self.transient(parent) if parent else None
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center(self):
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 600)
        h = max(self.winfo_reqheight(), 520)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # Header
        ctkh.header_strip(
            self, "SERVPRO  ·  Tech Roster",
            subtitle="Names here are recognized in Trello dispatch lines "
                     "across every EMS tool.")

        # Body — two stacked sections: hardcoded (read-only) + user-added.
        body = tk.Frame(self, bg=BG, padx=18, pady=12)
        body.pack(fill="both", expand=True)

        # --- Built-in roster (read-only) ---
        ctkh.h2(body, "Built-in techs (shipped with the tool)").pack(
            fill="x", anchor="w")
        ctkh.hint(body,
                  "These are baked into the build — to add or remove "
                  "one, edit audit_logic._HARDCODED_NAMES.",
                  wraplength=520).pack(fill="x")

        baked = self._format_baked_names()
        baked_frame = ctkh.card(body)
        baked_frame.pack(fill="x", pady=(6, 12))
        ctkh.ctk.CTkLabel(baked_frame, text=baked, font=ctkh.font(10),
                          text_color=TEXT_DARK,
                          anchor="w", justify="left",
                          wraplength=520
                          ).pack(fill="x", padx=10, pady=8)

        # --- User-added roster (editable) ---
        ur_hdr = tk.Frame(body, bg=BG)
        ur_hdr.pack(fill="x")
        ctkh.h2(ur_hdr, "Your added techs").pack(side="left")
        ctkh.ctk.CTkLabel(ur_hdr, text="(applied immediately on Save)",
                          font=ctkh.font(9),
                          text_color=TEXT_GRAY).pack(side="left", padx=(8, 0))

        # Listbox stays — CTk has no equivalent and the existing styling
        # (Consolas mono, green selection tint) already feels modern.
        lf = ctkh.card(body, fg_color=WHITE)
        lf.pack(fill="both", expand=True, pady=(4, 8))

        self._listbox = tk.Listbox(lf, font=("Consolas", 10),
                                   bg=WHITE, fg=TEXT_DARK,
                                   selectbackground="#E8F5EE",
                                   selectforeground=TEXT_DARK,
                                   relief="flat", borderwidth=0,
                                   height=8, activestyle="none")
        sb = tk.Scrollbar(lf, orient="vertical",
                          command=self._listbox.yview)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(sb)
        except Exception:
            pass
        self._listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._listbox.pack(side="left", fill="both", expand=True,
                           padx=4, pady=4)

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x")
        ctkh.btn(btn_row, "Remove selected", command=self._remove_selected,
                 kind="ghost", width=130, height=28
                 ).pack(side="left")

        # Add form — name + optional initials. CTkFrame with title label
        # replaces the LabelFrame (CTk has no equivalent; this looks better).
        addf = ctkh.card(body, fg_color=BG, border_width=1)
        addf.pack(fill="x", pady=(10, 0))
        ctkh.h2(addf, "Add a tech").pack(anchor="w", padx=10, pady=(8, 4))

        # Name row
        nrow = tk.Frame(addf, bg=BG)
        nrow.pack(fill="x", padx=10, pady=(0, 4))
        ctkh.ctk.CTkLabel(nrow, text="Name", font=ctkh.font(10),
                          text_color=TEXT_DARK, width=64, anchor="w"
                          ).pack(side="left")
        self._name_var = tk.StringVar()
        ent = ctkh.entry(nrow, textvariable=self._name_var, width=240)
        ent.pack(side="left", fill="x", expand=True)
        ctkh.ctk.CTkLabel(nrow, text="(e.g. Carlos, Mark T)",
                          font=ctkh.font(9),
                          text_color=TEXT_GRAY).pack(side="left", padx=(8, 0))

        # Initials row (optional)
        irow = tk.Frame(addf, bg=BG)
        irow.pack(fill="x", padx=10, pady=(0, 4))
        ctkh.ctk.CTkLabel(irow, text="Initials", font=ctkh.font(10),
                          text_color=TEXT_DARK, width=64, anchor="w"
                          ).pack(side="left")
        self._init_var = tk.StringVar()
        ctkh.entry(irow, textvariable=self._init_var, width=80
                   ).pack(side="left")
        ctkh.ctk.CTkLabel(
            irow,
            text="optional — only fill if dispatch lines write the "
                 "tech as initials (e.g. CL → Carlos)",
            font=ctkh.font(9),
            text_color=TEXT_GRAY,
            wraplength=380, justify="left"
        ).pack(side="left", padx=(8, 0))

        addbtn = tk.Frame(addf, bg=BG)
        addbtn.pack(fill="x", padx=10, pady=(2, 10))
        ctkh.btn(addbtn, "+ Add", command=self._add, kind="primary"
                 ).pack(side="right")

        # Enter in either field triggers add — feels faster than
        # mousing to the button.
        ent.bind("<Return>", lambda _e: self._add())

        # Footer — Save / Cancel
        bot = tk.Frame(self, bg=BG, padx=18, pady=12)
        bot.pack(fill="x")
        ctkh.btn(bot, "Cancel", command=self._on_close, kind="ghost",
                 width=90).pack(side="right", padx=(8, 0))
        ctkh.btn(bot, "Save", command=self._save, kind="primary",
                 width=110).pack(side="right")

    def _format_baked_names(self):
        """Pretty-print the hardcoded list for the read-only panel.
        Strip regex bits ('\\s*' between tokens, '?' makes the name look
        weird) so users see real names, not the raw regex."""
        out = []
        for raw in audit_logic._HARDCODED_NAMES:
            cleaned = (raw.replace(r'\s*', ' ')
                          .replace('?', '')
                          .strip())
            out.append(cleaned)
        # Sort for readable display, keep duplicates (initials tokens
        # like FB/ML/ME read distinctly from full names).
        out = sorted(set(out), key=str.lower)
        return ", ".join(out)

    def _render_user_list(self):
        self._listbox.delete(0, "end")
        for name in self._user_names:
            initials = next((k for k, v in self._user_abbrev.items()
                             if v == name), "")
            line = f"  {name:<24}  {initials}" if initials else f"  {name}"
            self._listbox.insert("end", line)
        if not self._user_names:
            self._listbox.insert("end", "  (no user-added techs yet)")
            self._listbox.itemconfig(0, fg=TEXT_GRAY)

    def _add(self):
        name = self._name_var.get().strip()
        initials = self._init_var.get().strip().upper()
        if not name:
            messagebox.showwarning(
                "Missing name",
                "Type a name first.", parent=self)
            return
        if name.lower() in {n.lower() for n in self._user_names}:
            messagebox.showwarning(
                "Already added",
                f"{name!r} is already in your list.", parent=self)
            return
        # Soft-collide with hardcoded — refuse so the user doesn't end up
        # with two entries pointing at the same regex token.
        for raw in audit_logic._HARDCODED_NAMES:
            cleaned = (raw.replace(r'\s*', ' ')
                          .replace('?', '')
                          .strip().lower())
            if cleaned == name.lower():
                messagebox.showinfo(
                    "Already built in",
                    f"{name!r} is already in the built-in roster — "
                    "no need to add it.", parent=self)
                return
        if initials and not initials.isalpha():
            messagebox.showwarning(
                "Bad initials",
                "Initials should be letters only (e.g. CL).",
                parent=self)
            return
        self._user_names.append(name)
        if initials:
            self._user_abbrev[initials] = name
        self._name_var.set("")
        self._init_var.set("")
        self._render_user_list()

    def _remove_selected(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._user_names):
            return
        name = self._user_names[idx]
        if not messagebox.askyesno(
            "Remove tech",
            f"Remove {name!r} from your roster?", parent=self):
            return
        self._user_names.pop(idx)
        # Also drop any abbrev entries that mapped to this name.
        self._user_abbrev = {k: v for k, v in self._user_abbrev.items()
                              if v != name}
        self._render_user_list()

    def _save(self):
        try:
            persistence.set_user_techs(self._user_names, self._user_abbrev)
            audit_logic.rebuild_tech_pattern()
        except Exception as ex:
            messagebox.showerror(
                "Save failed",
                f"Couldn't save tech roster:\n{ex}", parent=self)
            return
        self.saved = True
        if self.on_save:
            try:
                self.on_save()
            except Exception:
                pass
        self.destroy()

    def _on_close(self):
        self.destroy()


def open_tech_roster(parent=None, on_save=None):
    """Open the dialog. Returns True if user clicked Save."""
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        dlg = TechRosterDialog(root, on_save=on_save)
        root.wait_window(dlg)
        root.destroy()
        return dlg.saved
    dlg = TechRosterDialog(parent, on_save=on_save)
    parent.wait_window(dlg)
    return dlg.saved


def main(argv=None):
    open_tech_roster(parent=None)


if __name__ == "__main__":
    main()
