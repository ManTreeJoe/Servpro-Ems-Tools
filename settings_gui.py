"""
Settings dialog — edit the folder paths used by every EMS tool.

Used two ways:
  - First-run wizard, popped automatically on the first launch
  - Anytime via the gear icon in the launcher header

Saves to %APPDATA%\\Linguar Hub\\config.json so per-PC settings don't get
clobbered by a rebuild.
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import paths
import config
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    FLAG_RED, SUCCESS_FG, SUCCESS_HOVER, NEUTRAL_HOVER)
from tool_panel import ScrollableFrame
from ui_buttons import done_button, secondary_button


# Field definitions — (config_key, label, hint, picker_type)
# picker_type: "dir" → folder picker; "file" → file picker; "url" → text only
FIELDS = [
    ("audit_base",
     "Job folders root",
     r"e.g. X:\IE_Public — where year folders (2025, 2026) live",
     "dir"),
    ("runs_dir",
     "Daily run docs folder",
     "Folder that gets the daily run .docx files",
     "dir"),
    ("photos_root",
     "Photos root folder",
     "SharePoint-synced photos folder (per-tech subfolders)",
     "dir"),
    ("photos_extra_roots",
     "Additional photo roots",
     "Optional — one path per line. Extra SharePoint-synced libraries "
     "to scan during audit (e.g. when a tech uploads to a different "
     "site outside the per-tech structure).",
     "dirlist"),
    ("snapshot_template",
     "Snapshot fillable PDF template",
     "snapshot_handoff_fillable.pdf",
     "file"),
    ("snapshot_output",
     "Snapshot PDF output folder",
     "Where filled snapshot PDFs are written",
     "dir"),
    ("apa_monitor_root",
     "APA Monitor docs folder",
     r"e.g. X:\IE_Public\APA Monitor — daily APA .docx files live here",
     "dir"),
    ("workcenter_url",
     "Workcenter URL",
     "Link shown in audit for missing forms (and for Fernando's photos)",
     "url"),
    ("enable_workcenter_alpha",
     "Enable Workcenter ALPHA features",
     "Turns on the in-development Playwright-driven Workcenter "
     "integration (search, form/photo download). Off = main behavior.",
     "bool"),
    ("show_sort_files",
     "Show Sort Files in toolbar",
     "Off by default — most users already have the Desktop "
     "'Sort Files.bat' shortcut. Turn on to put a Sort Files button "
     "back in the launcher's top tool strip. Restart the launcher "
     "for this to take effect.",
     "bool"),
    ("show_new_job",
     "Show New EMS Job in toolbar",
     "Off by default — New Job is reachable as a button inside the "
     "Audit and Snapshot tools where job-creation actually happens. "
     "Turn on to also put a top-level launcher button back. Restart "
     "the launcher for this to take effect.",
     "bool"),
    ("trello_token",
     "Trello token (per-user)",
     "Your personal Trello token. Click Generate to authorize EMS "
     "Automation in your browser, then paste the token Trello shows. "
     "Each user has their own — comments you post appear under your name.",
     "trello_token"),
    ("appearance",
     "Appearance",
     "Light / Dark / System (follows your Windows theme). "
     "Applied immediately on Save — already-open tools may need to be "
     "closed and reopened to pick up the new palette fully.",
     "choice", ["system", "light", "dark"]),
    ("ui_scale",
     "UI scale",
     "Override automatic display-scaling detection. 'auto' uses the "
     "monitor's reported DPI. Bump higher if the app feels tiny on a "
     "4K laptop / small high-DPI screen, lower to fit more on screen. "
     "Restart Linguar Hub after changing.",
     "choice", ["auto", "1.0", "1.25", "1.5", "1.75",
                "2.0", "2.25", "2.5"]),
]


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent=None, first_run=False, on_save=None):
        super().__init__(parent) if parent else super().__init__()
        self.first_run = first_run
        self.on_save   = on_save
        self.saved     = False

        self.title("Linguar Hub Settings")
        self.configure(bg=BG)
        # Hide the window until layout + centering are done. Without
        # this the user sees the dialog flash at Tk's default top-left
        # position, render its widgets, then jump to the centered spot
        # — a visible half-load that reads as "loading bug". withdraw
        # ⇒ build ⇒ center ⇒ deiconify makes the dialog appear at its
        # final position with content already drawn.
        self.withdraw()
        # Vertical resize allowed so the user can grow the window when
        # the field list outgrows the screen on a small laptop. Width
        # stays locked because the form is single-column and resizing
        # horizontally would just stretch entry boxes.
        self.resizable(False, True)

        ico = paths.resource("wrench.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        try:
            self.cfg = config.load()
        except Exception:
            self.cfg = {}

        self._build_ui()
        self._center_on_screen()
        # Now visible at the final position with content already drawn.
        try:
            self.deiconify()
        except tk.TclError:
            pass
        self.transient(parent) if parent else None
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_on_screen(self):
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=GREEN, pady=14)
        hdr.pack(fill="x")
        title = "Welcome — set up your folders" if self.first_run else "Settings"
        tk.Label(hdr, text=f"SERVPRO  ·  {title}",
                 font=("Fraunces", 15, "bold"),
                 bg=GREEN, fg=WHITE).pack()
        sub = ("Pick the folders the tools should read and write to. "
               "You can change these later from the launcher's gear icon.") \
              if self.first_run else \
              "Edit the folders the tools read and write to."
        tk.Label(hdr, text=sub,
                 font=("Segoe UI Variable", 8),
                 bg=GREEN, fg="#B2DFC4", wraplength=520).pack(pady=(4, 0))

        # Scrolling form area — fields outgrew the screen on smaller
        # laptops once we added trello_token + workcenter + tech roster.
        # Wrap them in a ScrollableFrame so the dialog stays bounded
        # vertically and the user can scroll through fields. The bottom
        # button bar is packed BELOW with side="bottom" + fill="x" so
        # Save/Cancel are always anchored at the bottom of the window.
        # pack_propagate(False) on the canvas's parent keeps the inner
        # form's natural size from blowing the whole dialog up to the
        # height of every field combined.
        self._scroll = ScrollableFrame(self, bg=BG, canvas_bg=BG)
        self._scroll.canvas.configure(height=480, width=620)
        self._scroll.pack(fill="both", expand=True)
        body = tk.Frame(self._scroll.inner, bg=BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        self._vars = {}
        for entry in FIELDS:
            key, label, hint, kind = entry[0], entry[1], entry[2], entry[3]
            choices = entry[4] if len(entry) > 4 else None
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=(0, 10))

            # Choice — a Combobox with a fixed allowlist. Used for
            # enum-like settings (e.g. appearance: system/light/dark).
            if kind == "choice":
                tk.Label(row, text=label, font=("Segoe UI Variable", 9, "bold"),
                         bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
                tk.Label(row, text=hint, font=("Segoe UI Variable", 8),
                         bg=BG, fg=TEXT_GRAY, anchor="w",
                         wraplength=520, justify="left").pack(fill="x")
                current = str(self.cfg.get(key, choices[0])).lower()
                if current not in choices:
                    current = choices[0]
                var = tk.StringVar(value=current)
                self._vars[key] = var
                ttk.Combobox(row, textvariable=var, values=list(choices),
                             state="readonly", width=20
                             ).pack(anchor="w", pady=(2, 0))
                continue

            # Bool fields render as a single Checkbutton row — no path
            # picker, no entry box, no missing-file warning.
            if kind == "bool":
                var = tk.BooleanVar(value=bool(self.cfg.get(key, False)))
                self._vars[key] = var
                tk.Checkbutton(
                    row, text=label, variable=var,
                    font=("Segoe UI Variable", 9, "bold"),
                    bg=BG, fg=TEXT_DARK, activebackground=BG,
                    selectcolor=WHITE, anchor="w"
                ).pack(fill="x")
                tk.Label(row, text=hint, font=("Segoe UI Variable", 8),
                         bg=BG, fg=TEXT_GRAY, anchor="w",
                         wraplength=520, justify="left").pack(
                    fill="x", padx=(20, 0))
                continue

            # Trello token — masked Entry + "Generate token…" link button
            # that opens Trello's authorize URL in the user's browser. The
            # token is per-user (each franchise user authorizes themselves)
            # so comments posted from the suite show their real name.
            if kind == "trello_token":
                tk.Label(row, text=label, font=("Segoe UI Variable", 9, "bold"),
                         bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
                tk.Label(row, text=hint, font=("Segoe UI Variable", 8),
                         bg=BG, fg=TEXT_GRAY, anchor="w",
                         wraplength=520, justify="left").pack(fill="x")
                entry_row = tk.Frame(row, bg=BG)
                entry_row.pack(fill="x", pady=(2, 0))
                var = tk.StringVar(value=self.cfg.get(key, ""))
                self._vars[key] = var
                ent = ttk.Entry(entry_row, textvariable=var,
                                width=58, show="•")
                ent.pack(side="left", fill="x", expand=True)
                secondary_button(
                    entry_row, "Generate token…", padx=8, pady=2,
                    font=("Segoe UI Variable", 8),
                    command=self._open_trello_authorize
                ).pack(side="right", padx=(6, 0))
                # Live status — confirms a token is set without revealing it.
                status = tk.Label(row, text="", font=("Segoe UI Variable", 7),
                                  bg=BG, fg=TEXT_GRAY, anchor="w")
                status.pack(fill="x")
                def _update_token_status(*_a, v=var, s=status):
                    val = v.get().strip()
                    if not val:
                        s.config(text="(no token — comments can't post)",
                                 fg=FLAG_RED)
                    elif val.startswith("ATTA") and len(val) >= 60:
                        s.config(text="✓ token saved", fg=SUCCESS_FG)
                    else:
                        s.config(
                            text="⚠ doesn't look like a Trello token "
                                 "(should start with ATTA…)", fg=FLAG_RED)
                var.trace_add("write", _update_token_status)
                _update_token_status()
                continue

            # Dir-list — multi-line Text widget, one path per line. Each
            # line that resolves to an existing directory gets a green
            # ✓ next to it; unresolved entries are kept (so a temporarily
            # offline drive's path doesn't get wiped on save).
            if kind == "dirlist":
                tk.Label(row, text=label, font=("Segoe UI Variable", 9, "bold"),
                         bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
                tk.Label(row, text=hint, font=("Segoe UI Variable", 8),
                         bg=BG, fg=TEXT_GRAY, anchor="w",
                         wraplength=520, justify="left").pack(fill="x")
                txt_frame = tk.Frame(row, bg=BG)
                txt_frame.pack(fill="x", pady=(2, 0))
                txt = tk.Text(txt_frame, height=3, width=58,
                              font=("Segoe UI Variable", 9), wrap="none",
                              relief="solid", borderwidth=1,
                              highlightthickness=0)
                txt.pack(side="left", fill="x", expand=True)
                # Seed with existing config — accept either a list or a
                # single string for forward compatibility.
                existing = self.cfg.get(key, []) or []
                if isinstance(existing, str):
                    existing = [existing]
                txt.insert("1.0", "\n".join(existing))
                self._vars[key] = txt
                secondary_button(
                    txt_frame, "+ Add…", padx=8, pady=2,
                    font=("Segoe UI Variable", 8),
                    command=lambda t=txt: self._append_dir(t)
                ).pack(side="right", padx=(6, 0))
                continue

            tk.Label(row, text=label, font=("Segoe UI Variable", 9, "bold"),
                     bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
            tk.Label(row, text=hint, font=("Segoe UI Variable", 8),
                     bg=BG, fg=TEXT_GRAY, anchor="w").pack(fill="x")

            entry_row = tk.Frame(row, bg=BG)
            entry_row.pack(fill="x", pady=(2, 0))

            var = tk.StringVar(value=self.cfg.get(key, ""))
            self._vars[key] = var
            entry = ttk.Entry(entry_row, textvariable=var, width=58)
            entry.pack(side="left", fill="x", expand=True)

            # URL fields are plain text — no picker, no path-existence check.
            if kind in ("dir", "file"):
                secondary_button(
                    entry_row, "Browse…", padx=8, pady=2,
                    font=("Segoe UI Variable", 8),
                    command=lambda k=key, kind=kind: self._browse(k, kind),
                ).pack(side="right", padx=(6, 0))

                # Live "missing" hint underneath (filesystem fields only)
                status = tk.Label(row, text="", font=("Segoe UI Variable", 7),
                                  bg=BG, fg=FLAG_RED, anchor="w")
                status.pack(fill="x")
                var.trace_add("write",
                    lambda *_args, k=key, kind=kind, s=status: self._update_status(k, kind, s))
                self._update_status(key, kind, status)

        # Buttons — anchored to the bottom edge so they don't get pushed
        # off-screen when the form area scrolls. side="bottom" guarantees
        # Save / Cancel stay reachable regardless of dialog height.
        bot = tk.Frame(self, bg=BG, padx=18, pady=12)
        bot.pack(side="bottom", fill="x")

        # Left side — utility buttons
        secondary_button(bot, "Auto-detect", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._auto_detect).pack(side="left")
        secondary_button(bot, "Reset to defaults", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._reset_defaults
                          ).pack(side="left", padx=(6, 0))
        secondary_button(bot, "Open data folder", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._open_data_folder
                          ).pack(side="left", padx=(6, 0))
        secondary_button(bot, "Manage Tech Roster…", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._open_tech_roster
                          ).pack(side="left", padx=(6, 0))
        # Shared jobs DB — export to share with another user, import to
        # pick up theirs. Lives in Settings because it's an admin /
        # cross-machine action, not a daily-use tool.
        secondary_button(bot, "📤 Export jobs DB", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._export_jobs_db
                          ).pack(side="left", padx=(6, 0))
        secondary_button(bot, "📥 Import jobs DB", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._import_jobs_db
                          ).pack(side="left", padx=(6, 0))
        secondary_button(bot, "🔄 Sync from Trello", padx=10, pady=5,
                          font=("Segoe UI Variable", 8),
                          command=self._sync_jobs_db_from_trello
                          ).pack(side="left", padx=(6, 0))

        # Right side — primary actions
        cancel_text = "Skip for now" if self.first_run else "Cancel"
        secondary_button(bot, cancel_text, padx=14, pady=6,
                          command=self._on_close
                          ).pack(side="right", padx=(8, 0))
        done_button(bot, "Save", padx=18, pady=6,
                     command=self._save).pack(side="right")

    def _append_dir(self, txt_widget):
        """Pop a folder picker and append the chosen path to the
        multi-line dirlist Text widget. No-op if the user cancels."""
        chosen = filedialog.askdirectory(
            parent=self, title="Choose folder",
            initialdir=os.path.expanduser("~"))
        if not chosen:
            return
        chosen = os.path.normpath(chosen)
        existing = txt_widget.get("1.0", "end-1c").strip()
        if existing:
            txt_widget.insert("end", "\n" + chosen)
        else:
            txt_widget.insert("end", chosen)

    def _browse(self, key, kind):
        current = self._vars[key].get().strip()
        initial = current if current and os.path.isdir(
            current if kind == "dir" else os.path.dirname(current)) else os.path.expanduser("~")
        if kind == "dir":
            chosen = filedialog.askdirectory(
                parent=self, title="Choose folder", initialdir=initial)
        else:
            chosen = filedialog.askopenfilename(
                parent=self, title="Choose file", initialdir=initial,
                filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
        if chosen:
            self._vars[key].set(os.path.normpath(chosen))

    def _update_status(self, key, kind, label):
        v = self._vars[key].get().strip()
        if not v:
            label.config(text="(empty)")
            return
        ok = os.path.isdir(v) if kind == "dir" else os.path.isfile(v)
        if ok:
            label.config(text="✓ found", fg=SUCCESS_FG)
        else:
            label.config(text="⚠ not found on this PC (you can still save)",
                         fg=FLAG_RED)

    def _save(self):
        new_cfg = dict(self.cfg)
        for entry in FIELDS:
            key, kind = entry[0], entry[3]
            if kind == "bool":
                new_cfg[key] = bool(self._vars[key].get())
            elif kind == "dirlist":
                # Text widget — split on newlines, drop blanks, normalize.
                raw = self._vars[key].get("1.0", "end-1c")
                paths_list = []
                for line in raw.splitlines():
                    s = line.strip()
                    if s:
                        paths_list.append(os.path.normpath(s))
                new_cfg[key] = paths_list
            elif kind == "choice":
                new_cfg[key] = self._vars[key].get().strip().lower()
            else:
                new_cfg[key] = self._vars[key].get().strip()
        try:
            config.save(new_cfg)
        except OSError as ex:
            messagebox.showerror("Save failed",
                                 f"Couldn't write config:\n{ex}", parent=self)
            return
        paths.mark_configured()

        # Live-apply the appearance setting before destroying the
        # dialog. theme.set_mode persists, swaps the module-level
        # palette constants, and flips customtkinter's appearance mode
        # (CTk widgets re-theme automatically). Plain-tk widgets that
        # captured bg=BG at construction time can't pick up the new
        # palette without being rebuilt — we walk the live widget tree
        # and reconfigure the ones we can, then ask the launcher
        # (via on_save) to do a fuller rebuild for tools it can recreate.
        try:
            old_mode = (self.cfg.get("appearance") or "dark").lower()
        except Exception:
            old_mode = "dark"
        new_mode = (new_cfg.get("appearance") or "dark").lower()
        appearance_changed = (new_mode != old_mode)
        if appearance_changed:
            try:
                import theme as _theme
                resolved = _theme.set_mode(new_mode)
                # Re-apply the ttk theme against the root so Treeview /
                # Combobox / Scrollbar pick up the new palette without
                # waiting for the next launch.
                try:
                    root = self.winfo_toplevel()
                    while getattr(root, "master", None) is not None:
                        root = root.master
                    _theme.apply_ttk_theme(root)
                except Exception:
                    pass
            except Exception:
                resolved = new_mode
        self.saved = True
        if self.on_save:
            try:
                self.on_save(new_cfg)
            except Exception:
                pass
        self.destroy()
        # After the dialog closes, surface a follow-up note when the
        # theme changed so the user knows whether a full restart is
        # needed for any panels that still look "stale".
        if appearance_changed and self.on_save:
            try:
                from tkinter import messagebox as _mb
                _mb.showinfo(
                    "Theme applied",
                    f"Switched appearance to {new_mode!r}. Most surfaces "
                    "re-theme immediately; if a tool you have open still "
                    "shows the old colors, close and reopen it.")
            except Exception:
                pass

    def _on_close(self):
        # Even if the user skipped, mark configured so we don't pop again
        paths.mark_configured()
        self.destroy()

    def _reset_defaults(self):
        """Re-load the bundled default config into the form (does not save)."""
        if not messagebox.askyesno(
            "Reset to defaults",
            "Reset every field to the values shipped with Linguar Hub?\n\n"
            "(You'll still need to click Save to commit.)", parent=self):
            return
        default = paths.resource("config.json")
        try:
            import json
            with open(default, encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            messagebox.showerror("Reset failed",
                                 "Couldn't read the bundled default config.",
                                 parent=self)
            return
        for entry in FIELDS:
            key, kind = entry[0], entry[3]
            choices = entry[4] if len(entry) > 4 else None
            if kind == "bool":
                self._vars[key].set(bool(data.get(key, False)))
            elif kind == "dirlist":
                txt = self._vars[key]
                txt.delete("1.0", "end")
                vals = data.get(key, []) or []
                if isinstance(vals, str):
                    vals = [vals]
                txt.insert("1.0", "\n".join(vals))
            elif kind == "choice":
                val = str(data.get(key, choices[0] if choices else "")).lower()
                if choices and val not in choices:
                    val = choices[0]
                self._vars[key].set(val)
            else:
                self._vars[key].set(data.get(key, ""))

    def _open_trello_authorize(self):
        """Open Trello's app-authorize URL in the user's default browser.
        After they authorize, Trello shows a token they paste back into
        the field. We require the api_key to already be set (bundled
        config seeds it for franchise users)."""
        api_key = (self.cfg.get("trello_api_key") or "").strip()
        # Re-read live from the entry if the user just changed it (rare
        # but possible — ITs setting up a new install might paste both).
        if "trello_api_key" in self._vars:
            try:
                api_key = self._vars["trello_api_key"].get().strip() or api_key
            except Exception:
                pass
        if not api_key:
            messagebox.showerror(
                "Trello key missing",
                "No Trello API key is configured. The bundled Linguar Hub "
                "default should include one — reinstall or contact the "
                "person who built your install.",
                parent=self)
            return
        import urllib.parse
        import webbrowser
        url = "https://trello.com/1/authorize?" + urllib.parse.urlencode({
            "key":           api_key,
            "name":          "Linguar Hub",
            "expiration":    "never",
            "response_type": "token",
            "scope":         "read,write",
        })
        try:
            webbrowser.open(url)
        except Exception as ex:
            messagebox.showerror("Couldn't open browser",
                                 f"Open this URL manually:\n\n{url}\n\n{ex}",
                                 parent=self)
            return
        messagebox.showinfo(
            "Authorize EMS Automation",
            "Your browser is opening Trello's authorization page.\n\n"
            "1. Sign in to Trello if asked.\n"
            "2. Click 'Allow' to authorize EMS Automation.\n"
            "3. Trello shows a long token starting with ATTA…\n"
            "4. Copy that whole token and paste it into the "
            "Trello token field, then Save.",
            parent=self)

    def _open_data_folder(self):
        try:
            os.startfile(paths.DATA_DIR)
        except OSError as ex:
            messagebox.showerror("Couldn't open folder", str(ex), parent=self)

    def _open_tech_roster(self):
        # Lazy import — avoids pulling tech_roster_gui (and its tk symbols)
        # in for first-run wizard contexts where the user hasn't even
        # configured paths yet.
        try:
            from tech_roster_gui import open_tech_roster
        except Exception as ex:
            messagebox.showerror(
                "Couldn't open Tech Roster",
                f"Failed to load tech_roster_gui:\n{ex}", parent=self)
            return
        open_tech_roster(parent=self)

    def _export_jobs_db(self):
        """Dump the shared jobs DB to a JSON file the user can hand
        off to a teammate's Import. Default target is Downloads with
        a dated filename so successive exports don't overwrite."""
        from tkinter import filedialog
        import datetime as _dt
        try:
            import ems_db
        except Exception as ex:
            messagebox.showerror(
                "Couldn't load ems_db", str(ex), parent=self)
            return
        default_name = f"ems_jobs_{_dt.date.today():%Y-%m-%d}.json"
        path = filedialog.asksaveasfilename(
            parent=self, title="Export jobs DB",
            defaultextension=".json",
            initialfile=default_name,
            initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            summary = ems_db.export_db(path)
        except Exception as ex:
            messagebox.showerror(
                "Export failed", str(ex), parent=self)
            return
        messagebox.showinfo(
            "Export complete",
            f"Wrote {summary['jobs']} jobs · "
            f"{summary['links']} links · "
            f"{summary['aliases']} aliases\n\n{path}",
            parent=self)

    def _import_jobs_db(self):
        """Load a teammate's exported jobs DB into the local file.
        Defaults to upsert (merge); user can pick replace if they
        want a clean install."""
        from tkinter import filedialog
        try:
            import ems_db
        except Exception as ex:
            messagebox.showerror(
                "Couldn't load ems_db", str(ex), parent=self)
            return
        path = filedialog.askopenfilename(
            parent=self, title="Import jobs DB",
            initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        mode = messagebox.askyesno(
            "Import mode",
            "Click YES to UPSERT (merge into local DB, keep local-only jobs)\n\n"
            "Click NO to REPLACE (wipe local jobs + install from file)\n\n"
            "Recommended: YES (upsert) — preserves any jobs you've added\n"
            "locally that aren't in the imported file.",
            parent=self)
        mode_arg = "upsert" if mode else "replace"
        try:
            res = ems_db.import_db(path, mode=mode_arg)
        except Exception as ex:
            messagebox.showerror(
                "Import failed", str(ex), parent=self)
            return
        messagebox.showinfo(
            "Import complete",
            f"Mode: {mode_arg}\n\n"
            f"Jobs added: {res['jobs_added']}\n"
            f"Jobs updated: {res['jobs_updated']}\n"
            f"Links: {res['links']}\n"
            f"Aliases: {res['aliases']}",
            parent=self)

    def _sync_jobs_db_from_trello(self):
        """Refresh the jobs DB from the in-scope Trello boards. Long-
        running — confirm before kicking off."""
        if not messagebox.askyesno(
                "Sync from Trello",
                "Walk every in-scope Trello board and refresh the local "
                "jobs DB. This can take 30–60 seconds depending on "
                "how many cards you have open.\n\nProceed?",
                parent=self):
            return
        try:
            import ems_db
            res = ems_db.sync_from_trello()
        except Exception as ex:
            messagebox.showerror(
                "Sync failed", str(ex), parent=self)
            return
        messagebox.showinfo(
            "Sync complete",
            f"Boards scanned: {res['boards']}\n"
            f"Cards found:    {res['cards']}\n"
            f"Jobs upserted:  {res['jobs_upserted']}\n"
            f"Links added:    {res['links_added']}",
            parent=self)

    def _auto_detect(self):
        """Run filesystem auto-detection and overlay any finds onto the form."""
        detected = paths.auto_detect()
        if not detected:
            messagebox.showinfo(
                "Auto-detect",
                "No matching folders found. Use Browse to pick them manually.",
                parent=self)
            return
        # Map field kinds for the dirlist guard below.
        kinds = {entry[0]: entry[3] for entry in FIELDS}
        for key, value in detected.items():
            if key not in self._vars:
                continue
            if kinds.get(key) == "dirlist":
                # auto_detect doesn't surface multi-path fields today;
                # skip rather than crash on the missing .set().
                continue
            self._vars[key].set(value)
        found_list = "\n".join(f"  • {k}: {v}" for k, v in detected.items())
        messagebox.showinfo(
            "Auto-detect",
            f"Filled in {len(detected)} field(s):\n\n{found_list}\n\n"
            f"Click Save to commit, or edit before saving.",
            parent=self)


def open_settings(parent=None, first_run=False, on_save=None):
    """Open the settings dialog. Blocks on its own mainloop if no parent."""
    if parent is None:
        # Standalone — own root
        root = tk.Tk()
        root.withdraw()
        dlg = SettingsDialog(root, first_run=first_run, on_save=on_save)
        root.wait_window(dlg)
        root.destroy()
        return dlg.saved
    dlg = SettingsDialog(parent, first_run=first_run, on_save=on_save)
    parent.wait_window(dlg)
    return dlg.saved


def main(argv=None):
    """Entry point so the dispatcher can open Settings as a standalone tool."""
    open_settings(parent=None, first_run=False)


if __name__ == "__main__":
    main()
