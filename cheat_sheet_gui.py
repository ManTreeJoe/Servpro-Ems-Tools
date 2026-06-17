"""
Cheat Sheet viewer — table of contents + collapsible subsections + search.
Renders EMS_Admin_Cheat_Sheet.md as a navigable GUI instead of opening it
in Notepad.

This panel is the CTk pilot: chrome (header, search bar, scrollable frames)
uses customtkinter for a cleaner, modern look and built-in dark-mode support.
The markdown body is still rendered with tk.Text since CTk has no Text
equivalent and we need its bold/italic/code/highlight tags.
"""
import os
import re
import sys
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    BORDER, FLAG_RED, SURFACE_2,
                    SUCCESS_BG, SUCCESS_FG, DANGER_FG)
from tool_panel import ToolPanel, ScrollableFrame, run_standalone
from ui_buttons import secondary_button

try:
    import customtkinter as ctk
    _HAVE_CTK = True
except ImportError:
    ctk = None
    _HAVE_CTK = False

_MD_PATH = paths.resource("EMS_Admin_Cheat_Sheet.md")
_ICON    = paths.resource("wrench.ico")


# ── Markdown parsing ─────────────────────────────────────────────────────────

def parse_markdown(path):
    """
    Returns: list of {title, subsections}
    where each subsection is {title, lines}
    Sections split on ## headings; subsections on ###.
    Content above the first ## becomes an 'Overview' section.
    """
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    sections = []
    cur_sec  = {"title": "Overview", "subsections": [{"title": "", "lines": []}]}

    for line in raw.splitlines():
        if line.startswith("# "):
            # Top-level title — skip; we use window title instead
            continue
        if line.startswith("## "):
            # New section
            if any(sub["lines"] or sub["title"] for sub in cur_sec["subsections"]):
                sections.append(cur_sec)
            cur_sec = {"title": line[3:].strip(),
                       "subsections": [{"title": "", "lines": []}]}
            continue
        if line.startswith("### "):
            cur_sec["subsections"].append({"title": line[4:].strip(), "lines": []})
            continue
        cur_sec["subsections"][-1]["lines"].append(line)

    if any(sub["lines"] or sub["title"] for sub in cur_sec["subsections"]):
        sections.append(cur_sec)
    return sections


# ── GUI ──────────────────────────────────────────────────────────────────────

class CheatSheetApp(ToolPanel):
    TOOL_TITLE        = "EMS Cheat Sheet"
    TOOL_AUMID        = "Servpro.EMS.CheatSheet"
    TOOL_GEOMETRY_KEY = "cheat_sheet"
    DEFAULT_GEOMETRY  = "1050x720"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("EMS Cheat Sheet")
        # Restore last standalone window size/position (no-op when embedded)
        self.restore_geometry()
        self.minsize(700, 420)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if os.path.isfile(_ICON):
            try:
                self.iconbitmap(default=_ICON)
                self.iconbitmap(_ICON)
            except Exception:
                pass

        self.sections = parse_markdown(_MD_PATH)
        self._collapsed = set()  # subsection keys collapsed
        self._current_idx = 0
        self._search_term = ""

        self._build_ui()
        if self.sections:
            self._show_section(0)

    # ── UI build ────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header — skipped when embedded (launcher already shows the title)
        if not self._embedded:
            if _HAVE_CTK:
                hdr = ctk.CTkFrame(self, fg_color=GREEN, corner_radius=0,
                                   height=58)
                hdr.pack(fill="x")
                hdr.pack_propagate(False)
                ctk.CTkLabel(hdr, text="SERVPRO  ·  EMS Cheat Sheet",
                             font=ctk.CTkFont("Fraunces", 15, "bold"),
                             text_color=WHITE).pack(pady=(8, 0))
                ctk.CTkLabel(hdr, text="Workflow reference — searchable",
                             font=ctk.CTkFont("Segoe UI Variable", 9),
                             text_color="#B2DFC4").pack(pady=(0, 6))
            else:
                hdr = tk.Frame(self, bg=GREEN, pady=10)
                hdr.pack(fill="x")
                tk.Label(hdr, text="SERVPRO  ·  EMS Cheat Sheet",
                         font=("Fraunces", 15, "bold"),
                         bg=GREEN, fg=WHITE).pack()
                tk.Label(hdr, text="Workflow reference — searchable",
                         font=("Segoe UI Variable", 9), bg=GREEN,
                         fg="#B2DFC4").pack(pady=(2, 0))

        # Search bar
        if _HAVE_CTK:
            sbar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
            sbar.pack(fill="x", padx=12, pady=(8, 4))
            ctk.CTkLabel(sbar, text="🔍  Search",
                         font=ctk.CTkFont("Segoe UI Variable", 9, "bold"),
                         text_color=TEXT_DARK
                         ).pack(side="left", padx=(0, 8))
            self._search_var = tk.StringVar()
            self._search_var.trace_add("write", lambda *_: self._on_search())
            ctk.CTkEntry(sbar, textvariable=self._search_var,
                         font=ctk.CTkFont("Segoe UI Variable", 10),
                         height=30, corner_radius=6
                         ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(sbar, text="Clear", width=70, height=30,
                          font=ctk.CTkFont("Segoe UI Variable", 9),
                          fg_color="#E5E7EA", hover_color="#D5D8DC",
                          text_color=TEXT_DARK, corner_radius=6,
                          command=lambda: self._search_var.set("")
                          ).pack(side="left", padx=(8, 0))
        else:
            sbar = tk.Frame(self, bg=BG, padx=12, pady=8)
            sbar.pack(fill="x")
            tk.Label(sbar, text="🔍 Search:", font=("Segoe UI Variable", 9, "bold"),
                     bg=BG, fg=TEXT_DARK).pack(side="left", padx=(0, 6))
            self._search_var = tk.StringVar()
            self._search_var.trace_add("write", lambda *_: self._on_search())
            ent = ttk.Entry(sbar, textvariable=self._search_var,
                            font=("Segoe UI Variable", 10))
            ent.pack(side="left", fill="x", expand=True)
            secondary_button(sbar, "Clear",
                              command=lambda: self._search_var.set("")
                              ).pack(side="left", padx=(6, 0))

        # Body: TOC | Content
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        # ── TOC (left) ──────────────────────────────────────────────────────
        # Both branches now use the canonical ScrollableFrame from
        # tool_panel — its panel-scoped bindtag wheel handler avoids
        # the bind_all leak that broke the right-pane scrolling when
        # CTk's internal wheel binding fought the TOC's own one.
        # Keeping the CTk-styled wrapper / label for visual parity
        # when CTk is available.
        if _HAVE_CTK:
            toc_wrap = ctk.CTkFrame(body, fg_color=WHITE, corner_radius=8,
                                    border_width=1, border_color=BORDER,
                                    width=240)
            toc_wrap.pack(side="left", fill="y", padx=(0, 8))
            toc_wrap.pack_propagate(False)
            ctk.CTkLabel(toc_wrap, text="Contents",
                         font=ctk.CTkFont("Segoe UI Variable", 9, "bold"),
                         fg_color=GREEN, text_color=WHITE,
                         corner_radius=0, height=24
                         ).pack(fill="x")
        else:
            toc_wrap = tk.Frame(body, bg=WHITE,
                                highlightthickness=1, highlightbackground=BORDER,
                                width=240)
            toc_wrap.pack(side="left", fill="y", padx=(0, 8))
            toc_wrap.pack_propagate(False)
            tk.Label(toc_wrap, text="Contents",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=GREEN, fg=WHITE, pady=4).pack(fill="x")
        self._toc_scroll = ScrollableFrame(toc_wrap, bg=WHITE)
        self._toc_scroll.pack(fill="both", expand=True)
        self._toc_inner = self._toc_scroll.inner

        # ── Content (right) ─────────────────────────────────────────────────
        # Same swap as TOC — keep CTk visual chrome, use ScrollableFrame
        # for the actual scroll body so wheel events stay panel-scoped.
        if _HAVE_CTK:
            cwrap = ctk.CTkFrame(body, fg_color=WHITE, corner_radius=8,
                                 border_width=1, border_color=BORDER)
            cwrap.pack(side="left", fill="both", expand=True)
            ctop = ctk.CTkFrame(cwrap, fg_color=GREEN, corner_radius=0,
                                height=28)
            ctop.pack(fill="x")
            ctop.pack_propagate(False)
            self._content_title = ctk.CTkLabel(
                ctop, text="", font=ctk.CTkFont("Segoe UI Variable", 11, "bold"),
                fg_color=GREEN, text_color=WHITE)
            self._content_title.pack(side="left", padx=10)
        else:
            cwrap = tk.Frame(body, bg=WHITE,
                             highlightthickness=1, highlightbackground=BORDER)
            cwrap.pack(side="left", fill="both", expand=True)

            ctop = tk.Frame(cwrap, bg=GREEN, pady=4)
            ctop.pack(fill="x")
            self._content_title = tk.Label(ctop, text="",
                                            font=("Segoe UI Variable", 11, "bold"),
                                            bg=GREEN, fg=WHITE, padx=10)
            self._content_title.pack(side="left")

        self._content_scroll = ScrollableFrame(cwrap, bg=WHITE)
        self._content_scroll.pack(fill="both", expand=True)
        self._content_inner = self._content_scroll.inner
        # Kept on the instance so _show_section can reset scroll to top.
        self._content_canvas = self._content_scroll.canvas

        self._render_toc()

    # ── TOC ─────────────────────────────────────────────────────────────────
    def _render_toc(self):
        for w in self._toc_inner.winfo_children():
            w.destroy()
        term = self._search_term.lower()

        for idx, sec in enumerate(self.sections):
            match_count = self._count_matches(sec, term) if term else None
            if term and match_count == 0:
                continue

            is_current = (idx == self._current_idx)
            row_bg = "#E8F5EE" if is_current else WHITE
            row = tk.Frame(self._toc_inner, bg=row_bg, padx=10, pady=4,
                           cursor="hand2")
            row.pack(fill="x")

            label_text = sec["title"]
            if match_count is not None:
                label_text += f"  ({match_count})"

            lbl = tk.Label(row, text=label_text,
                            font=("Segoe UI Variable", 9,
                                  "bold" if is_current else "normal"),
                            bg=row_bg,
                            fg=GREEN_DARK if is_current else TEXT_DARK,
                            anchor="w", cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)

            def _click(i=idx):
                self._show_section(i)
            row.bind("<Button-1>", lambda e, i=idx: _click(i))
            lbl.bind("<Button-1>", lambda e, i=idx: _click(i))

    def _count_matches(self, section, term):
        if not term:
            return 0
        count = 0
        for sub in section["subsections"]:
            if term in sub["title"].lower():
                count += 1
            for line in sub["lines"]:
                count += line.lower().count(term)
        return count

    # ── Content ─────────────────────────────────────────────────────────────
    def _show_section(self, idx):
        if idx < 0 or idx >= len(self.sections):
            return
        self._current_idx = idx
        section = self.sections[idx]
        self._content_title.configure(text=section["title"])

        for w in self._content_inner.winfo_children():
            w.destroy()

        for sub_idx, sub in enumerate(section["subsections"]):
            self._render_subsection(idx, sub_idx, sub)

        # Restore scroll to top — single path now that both CTk and
        # non-CTk branches use ScrollableFrame underneath.
        self.update_idletasks()
        try:
            self._content_canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        self._render_toc()  # refresh active highlight

    def _render_subsection(self, sec_idx, sub_idx, sub):
        key = f"{sec_idx}::{sub_idx}"
        collapsed = key in self._collapsed

        wrap = tk.Frame(self._content_inner, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="x", padx=8, pady=(6, 2))

        if sub["title"]:
            hdr = tk.Frame(wrap, bg=SUCCESS_BG, padx=10, pady=5, cursor="hand2")
            hdr.pack(fill="x")
            arrow = "▶" if collapsed else "▼"
            lbl = tk.Label(hdr, text=f"{arrow}  {sub['title']}",
                            font=("Segoe UI Variable", 10, "bold"),
                            bg=SUCCESS_BG, fg=SUCCESS_FG)
            lbl.pack(side="left")
            def _toggle(k=key):
                if k in self._collapsed:
                    self._collapsed.discard(k)
                else:
                    self._collapsed.add(k)
                self._show_section(sec_idx)
            hdr.bind("<Button-1>", lambda e: _toggle())
            lbl.bind("<Button-1>", lambda e: _toggle())

        if collapsed:
            return

        body = tk.Frame(wrap, bg=WHITE, padx=12, pady=6)
        body.pack(fill="x")

        # Render lines using Text widget so we get bold + highlights
        text = tk.Text(body, wrap="word", font=("Segoe UI Variable", 10),
                       bg=WHITE, relief="flat", borderwidth=0,
                       padx=4, pady=4, height=1, cursor="arrow")
        text.pack(fill="x")

        # Configure tags
        text.tag_configure("bold", font=("Segoe UI Variable", 10, "bold"))
        text.tag_configure("italic", font=("Segoe UI Variable", 10, "italic"))
        text.tag_configure("code", font=("Consolas", 9),
                            background=SURFACE_2, foreground=DANGER_FG)
        text.tag_configure("bullet", lmargin1=14, lmargin2=28)
        text.tag_configure("nested_bullet", lmargin1=28, lmargin2=42)
        text.tag_configure("highlight", background="#FFF38A",
                           foreground="#1C1815")
        text.tag_configure("hr", foreground=BORDER)

        in_code_block = False
        for raw_line in sub["lines"]:
            if raw_line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                text.insert("end", raw_line + "\n", "code")
                continue
            line = raw_line.rstrip()
            if not line.strip():
                text.insert("end", "\n")
                continue
            if line.strip() == "---":
                text.insert("end", "─" * 60 + "\n", "hr")
                continue
            self._render_line(text, line)

        # Auto-size to content (no scroll inside subsection)
        text.update_idletasks()
        line_count = int(text.index("end-1c").split(".")[0])
        text.config(height=max(1, line_count + 1), state="disabled")

        # Apply search highlights
        if self._search_term:
            self._highlight_matches(text, self._search_term)

    def _render_line(self, text, line):
        """Render a single markdown line with bold/italic/code tags."""
        # Detect bullet
        lstripped = line.lstrip()
        indent = len(line) - len(lstripped)
        bullet_tag = None
        if lstripped.startswith("- "):
            bullet_tag = "nested_bullet" if indent >= 2 else "bullet"
            lstripped = "•  " + lstripped[2:]
        elif re.match(r'^\d+\.\s', lstripped):
            bullet_tag = "nested_bullet" if indent >= 2 else "bullet"

        # Tokenize bold/italic/code
        # Pattern: **bold**, *italic*, `code`
        pattern = re.compile(r'(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)')
        parts = pattern.split(lstripped)

        for part in parts:
            if not part:
                continue
            tags = ()
            if bullet_tag:
                tags = (bullet_tag,)
            if part.startswith("**") and part.endswith("**"):
                text.insert("end", part[2:-2], tags + ("bold",))
            elif part.startswith("`") and part.endswith("`"):
                text.insert("end", part[1:-1], tags + ("code",))
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                text.insert("end", part[1:-1], tags + ("italic",))
            else:
                text.insert("end", part, tags)
        text.insert("end", "\n", (bullet_tag,) if bullet_tag else ())

    def _highlight_matches(self, text, term):
        """Tag every case-insensitive occurrence of `term` with the highlight tag."""
        pos = "1.0"
        term_low = term.lower()
        all_text = text.get("1.0", "end-1c").lower()
        offset = 0
        while True:
            idx = all_text.find(term_low, offset)
            if idx < 0:
                break
            start = f"1.0 + {idx} chars"
            end   = f"1.0 + {idx + len(term)} chars"
            text.tag_add("highlight", start, end)
            offset = idx + max(1, len(term))

    # ── Search ──────────────────────────────────────────────────────────────
    def _on_search(self):
        self._search_term = self._search_var.get().strip()
        # Refresh both the TOC (filter sections) and current content (highlights)
        # If current section now has 0 matches, jump to first match.
        if self._search_term:
            term = self._search_term.lower()
            counts = [self._count_matches(s, term) for s in self.sections]
            if all(c == 0 for c in counts):
                pass  # nothing to do, all sections empty
            elif counts[self._current_idx] == 0:
                first = next((i for i, c in enumerate(counts) if c > 0), 0)
                self._show_section(first)
                return
        self._show_section(self._current_idx)


    def _on_close(self):
        # No-op when embedded (where self.geometry() would return the
        # launcher's geometry, not ours).
        self.save_geometry()
        self.destroy()


def main(argv=None):
    # run_standalone honors CheatSheetApp.TOOL_GEOMETRY_KEY automatically.
    run_standalone(CheatSheetApp, geometry="1050x720", minsize=(700, 420))


if __name__ == "__main__":
    main()
