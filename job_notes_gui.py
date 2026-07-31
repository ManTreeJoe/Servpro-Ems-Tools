"""
Job Notes — paste/edit Trello notes per client, see timeline + expected files.

Notes save to %APPDATA%\\Linguar Hub\\notes\\<year>\\<client>.md so they
persist across sessions and are private to the user. The panel auto-parses
pasted text for activity keywords (initial / mold prep / demo / monitor /
teardown / recon / reinspect) and renders:
  • a vertical timeline of stages seen (latest highlighted)
  • an "Expected Files" card listing what photos should exist at this stage

Export options: per-client "Save As" or bulk export of the entire notes/
tree to a user-picked folder.
"""
import os
import re
import sys
import shutil
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_logic
import ctk_helpers as ctkh
import paths
import persistence
import trello_client
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    TEXT_MUTED, BORDER, FLAG_RED, SURFACE_2,
                    NEUTRAL_HOVER,
                    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER, LINK_FG,
                    INFO_BG, INFO_FG, INFO_HOVER, WARN_BG, WARN_FG,
                    WARN_HOVER, DANGER_BG, DANGER_FG)
from tool_panel import (ToolPanel, run_standalone, show_toast, notify_error,
                         ScrollableFrame)
from trello_icon import trello_icon
from ui_buttons import (done_button, send_button, link_button,
                          secondary_button, icon_button, trello_link_button)

AUDIT_BASE = paths.audit_base()
_ICON = paths.resource("wrench.ico")

# Notes logic lives in job_notes_logic (UI-free, shared with the web panels).
# Re-export the names this module + its callers use so the Tk UI keeps working
# unchanged and external importers are unaffected. See EMS_Tk_Extraction_Plan.md.
from job_notes_logic import (  # noqa: E402
    _NOTES_ROOT, STAGES, parse_stages, expected_files,
    clean_trello_paste, _safe_filename, _notes_path,
    load_note, find_any_note_for_client, save_note,
    has_note, has_any_note_for_client, list_saved_notes,
)


# ── Comment rendering (editor-only) ──────────────────────────────────────────
# Header pattern for the CLEANED output ("Author · Date"). Used by the
# editor's tagger so each comment renders as a green-banded card. The
# trailing "(edited)" marker is optional — Trello shows it on comments
# that were modified after posting and we preserve it on the cleaned
# output as a useful signal to the user.
_RENDERED_HEADER_RE = re.compile(
    r"^[A-Za-z][\w'.\-]*(?:[ \t]+[A-Za-z][\w'.\-]*)*[ \t]*·[ \t]*"
    r"[A-Z][a-z]{2}[ \t]+\d{1,2},[ \t]+\d{4},[ \t]+"
    r"\d{1,2}:\d{2}[ \t]*[AP]M"
    r"(?:[ \t]+\(edited\))?"
    r"[ \t]*$",
    re.MULTILINE
)

# ── Lightweight markdown rendering ──────────────────────────────────────────
# Notes are stored as plain markdown so the .md export and external editors
# stay simple, but the editor visually styles common markers in place so the
# pane reads more like Notion / GitHub-preview than raw text. Markers (#, **,
# *, `, leading -) get elided via the md_marker tag so the user sees the
# styled content without the punctuation noise. Search still works because
# only the markers are hidden, not the content underneath.
_MD_HEADER_RE = re.compile(r"^(#{1,3}) +(.+)$", re.MULTILINE)
_MD_BOLD_RE   = re.compile(r"\*\*([^*\n]+?)\*\*")
# Italic must NOT eat into a `**bold**` span — guard with negative
# look-around for adjacent asterisks.
_MD_ITALIC_RE = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?![\*\w])")
_MD_CODE_RE   = re.compile(r"`([^`\n]+?)`")
# Bullets — line starts with "- " or "* " followed by anything. Note: the
# bullet's leading "*" can't be confused with italic since italic needs a
# closing "*" on the same line.
_MD_BULLET_RE = re.compile(r"^([-*])( +)(.+)$", re.MULTILINE)

# clean_trello_paste + note storage (parse_stages, save_note, load_note,
# list_saved_notes, …) now live in job_notes_logic and are re-exported via
# the shim import near the top of this file.


# ── Trello hover cache ──────────────────────────────────────────────────────
# Many jobs have no local .md cache but DO have an active Trello card with
# the running activity feed. The Job Notes editor fetches that text on
# `_load_client`; the hover popover doesn't (it's read-only). Without this
# cache, the hover says "No notes yet" on every job whose user has never
# clicked the 🗒 icon, even though Trello has the full story.
#
# Strategy: in-process LRU-ish dict keyed by Trello card_id. First hover
# kicks off a background fetch (non-blocking) and renders the still-empty
# state with a "Fetching from Trello…" hint; subsequent hovers within
# `_TRELLO_HOVER_TTL_S` get the cached text instantly. Cache is wiped on
# process restart — short-lived enough that staleness isn't a concern for
# a hover-glance affordance.
_TRELLO_HOVER_CACHE: dict[str, tuple[float, str]] = {}
_TRELLO_HOVER_INFLIGHT: set[str] = set()
_TRELLO_HOVER_TTL_S = 300  # 5 minutes


def _trello_hover_text(card_ids):
    """Return the freshest cached Trello activity feed across `card_ids`,
    or '' if nothing is cached / cache is stale."""
    if not card_ids:
        return ""
    import time as _t
    now = _t.time()
    best = ""
    best_ts = 0.0
    for cid in card_ids:
        entry = _TRELLO_HOVER_CACHE.get(cid)
        if not entry:
            continue
        ts, txt = entry
        if (now - ts) >= _TRELLO_HOVER_TTL_S:
            continue
        if ts > best_ts and txt and txt.strip():
            best_ts = ts
            best = txt
    return best


def _warm_trello_hover_cache(card_ids, *, on_done=None):
    """Background fetch — populates `_TRELLO_HOVER_CACHE` for any card_ids
    that don't already have a fresh entry. Threaded so the hover render
    stays snappy. `on_done(cid, text)` fires per-card on the worker thread
    once a card lands — caller is responsible for marshalling to the UI
    thread if it touches widgets."""
    if not card_ids:
        return
    pending = [cid for cid in card_ids
               if cid and cid not in _TRELLO_HOVER_INFLIGHT]
    if not pending:
        return
    for cid in pending:
        _TRELLO_HOVER_INFLIGHT.add(cid)

    def _do():
        import time as _t
        import trello_client as _tc
        for cid in pending:
            try:
                # Re-check freshness — another caller may have warmed
                # this card between the dispatch and worker start.
                entry = _TRELLO_HOVER_CACHE.get(cid)
                if entry and (_t.time() - entry[0]) < _TRELLO_HOVER_TTL_S:
                    continue
                card = _tc.get_card(cid)
                if not card:
                    continue
                try:
                    lane = _tc.get_lane_name(card.get("idBoard"),
                                              card.get("idList"))
                except Exception:
                    lane = ""
                try:
                    text = _tc.format_activity_feed(card, lane_name=lane)
                except Exception:
                    text = ""
                if text and text.strip():
                    _TRELLO_HOVER_CACHE[cid] = (_t.time(), text)
                    if on_done is not None:
                        try:
                            on_done(cid, text)
                        except Exception:
                            pass
            except Exception:
                # Network/auth failure — silently skip; the hover will
                # keep showing the "no notes" fallback.
                pass
            finally:
                _TRELLO_HOVER_INFLIGHT.discard(cid)
    import threading
    threading.Thread(target=_do, daemon=True).start()


def build_hover_popover(parent, year, client):
    """Populate `parent` (a tk.Frame) with the Job Notes hover popover —
    a 2-section read-out of:
      • Timeline — every detected stage in canonical order, with the
        latest stage emphasized.
      • Expected files — the union of expected-files lists for the
        stages reached so far, mirroring the right-hand pane of the
        Job Notes editor.

    Caller is responsible for triggering the hover (see
    `tool_panel.attach_rich_tooltip`). All exceptions are swallowed by
    the rich-tooltip host so this can read the .md file without
    crashing a hover.
    """
    from theme import SURFACE_2 as _SF2, TEXT_DARK as _TXD, TEXT_GRAY as _TXG
    try:
        from theme import ACCENT_PRIMARY as _ACC
    except Exception:
        _ACC = _TXD
    text = ""
    try:
        text = load_note(year, client) or ""
    except Exception:
        text = ""
    # Cross-year .md lookup — the year derived from the audit row's path
    # can mismatch the year the note was saved under (job carried over
    # from prior year, user-edited note tool wrote under today's year
    # while the job folder still lives in last year's tree, etc.).
    if not text.strip():
        try:
            _y, _t = find_any_note_for_client(client)
            if _t and _t.strip():
                text = _t
        except Exception:
            pass
    # Trello live-feed fallback — for jobs with a pinned card but no
    # local .md (common: user never opened the notes panel for this
    # client). Reads from an in-process cache populated by background
    # fetches. First hover gets a "Fetching…" message; subsequent
    # hovers within the cache TTL show the full Trello activity feed.
    trello_loading = False
    if not text.strip():
        try:
            import persistence as _per
            card_ids = _per.get_trello_card_ids(client) or []
        except Exception:
            card_ids = []
        if card_ids:
            cached = _trello_hover_text(card_ids)
            if cached:
                text = cached
            else:
                trello_loading = True
                _warm_trello_hover_cache(card_ids)
    # Final fallback — legacy persistence note store. Mirrors the
    # button's has-note check (persistence.has_note OR .md), so the
    # hover never claims "no notes" on a client whose icon is dark.
    if not text.strip():
        try:
            import persistence as _per
            text = _per.get_note(client) or ""
        except Exception:
            pass
    stages = parse_stages(text)
    files = expected_files(stages)

    # Header — client name (small) so the popover stands on its own when
    # multiple rows are hovered in quick succession.
    tk.Label(parent, text=client or "(no client)",
             font=("Segoe UI Variable", 9, "bold"),
             bg=_SF2, fg=_TXD, anchor="w").pack(anchor="w")

    if not text.strip():
        if trello_loading:
            tk.Label(parent,
                     text="📋 Fetching from Trello — hover again in a "
                          "moment to see the feed.",
                     font=("Segoe UI Variable", 8),
                     bg=_SF2, fg=_TXG, anchor="w",
                     wraplength=300, justify="left"
                     ).pack(anchor="w", pady=(4, 0))
        else:
            tk.Label(parent, text="No notes yet — click 🗒 to create.",
                     font=("Segoe UI Variable", 8),
                     bg=_SF2, fg=_TXG, anchor="w",
                     wraplength=300, justify="left"
                     ).pack(anchor="w", pady=(4, 0))
        return

    # ── Timeline ─────────────────────────────────────────────────────
    tk.Label(parent, text="Timeline",
             font=("Segoe UI Variable", 8, "bold"),
             bg=_SF2, fg=_TXG, anchor="w").pack(anchor="w", pady=(6, 0))
    if not stages:
        tk.Label(parent, text="(no recognized stages yet)",
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=_SF2, fg=_TXG, anchor="w").pack(anchor="w", padx=(8, 0))
    else:
        latest = stages[-1]
        for s in stages:
            is_latest = (s == latest)
            tk.Label(
                parent,
                text=("● " if is_latest else "○ ") + s,
                font=("Segoe UI Variable", 8,
                      "bold" if is_latest else "normal"),
                bg=_SF2,
                fg=_ACC if is_latest else _TXD,
                anchor="w",
            ).pack(anchor="w", padx=(8, 0))

    # ── Expected files ───────────────────────────────────────────────
    tk.Label(parent, text="Expected files",
             font=("Segoe UI Variable", 8, "bold"),
             bg=_SF2, fg=_TXG, anchor="w").pack(anchor="w", pady=(6, 0))
    if not files:
        tk.Label(parent, text="(none for this stage)",
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=_SF2, fg=_TXG, anchor="w").pack(anchor="w", padx=(8, 0))
    else:
        for f in files:
            tk.Label(parent, text="• " + f,
                     font=("Segoe UI Variable", 8),
                     bg=_SF2, fg=_TXD, anchor="w"
                     ).pack(anchor="w", padx=(8, 0))

    # ── Current audit status ────────────────────────────────────────
    # Pull this client's most-recent backlog entry. Shows FLAG/PASS
    # status, top missing items, and the audit_count badge so the
    # user knows at-a-glance whether this job is currently flagged
    # AND whether it's been flagged repeatedly.
    backlog_row = None
    try:
        import audit_export
        for j in audit_export.load_audit_backlog().get("jobs", []):
            jc = (j.get("client") or "").strip()
            if jc and jc.casefold() == (client or "").casefold():
                backlog_row = j
                break
    except Exception:
        backlog_row = None

    if backlog_row is not None:
        status = (backlog_row.get("status") or "").upper()
        cnt = int(backlog_row.get("audit_count") or 0)
        try:
            from theme import FLAG_RED as _FR, GREEN_DARK as _GD
        except Exception:
            _FR, _GD = "#A64242", "#1E7A3D"
        status_color = (_FR if status == "FLAG"
                        else _GD if status in ("PASS", "OK") else _TXD)
        tk.Label(parent, text="Audit status",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=_SF2, fg=_TXG, anchor="w").pack(anchor="w", pady=(6, 0))
        head = tk.Frame(parent, bg=_SF2)
        head.pack(anchor="w", padx=(8, 0))
        tk.Label(head, text=status or "(unknown)",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=_SF2, fg=status_color).pack(side="left")
        if cnt > 1:
            tk.Label(head, text=f"  ×{cnt} audits",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=_SF2, fg=_TXG).pack(side="left", padx=(6, 0))

        # Issue list — cap at 6 lines (3 forms + 3 photos) so the
        # popover doesn't dwarf the timeline section.
        form_issues = (backlog_row.get("form_issues") or [])[:3]
        photo_issues = (backlog_row.get("photo_issues") or [])[:3]
        for iss in form_issues:
            tk.Label(parent, text=f"• 📄 {iss}",
                     font=("Segoe UI Variable", 8),
                     bg=_SF2, fg=_TXD, anchor="w"
                     ).pack(anchor="w", padx=(8, 0))
        for iss in photo_issues:
            tk.Label(parent, text=f"• 📷 {iss}",
                     font=("Segoe UI Variable", 8),
                     bg=_SF2, fg=_TXD, anchor="w"
                     ).pack(anchor="w", padx=(8, 0))
        extra = ((len(backlog_row.get("form_issues") or []) - 3)
                 + (len(backlog_row.get("photo_issues") or []) - 3))
        if extra > 0:
            tk.Label(parent, text=f"  …+{extra} more",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=_SF2, fg=_TXG, anchor="w"
                     ).pack(anchor="w", padx=(8, 0))


def migrate_legacy_note(year, client, legacy_text, clear_legacy=None):
    """One-time copy from persistence-backed notes into the .md store.

    Idempotent: skips if a .md already exists, or if legacy_text is empty.
    On successful migration, calls clear_legacy() so the old store empties.
    """
    if not legacy_text or not legacy_text.strip():
        return False
    if has_note(year, client):
        return False
    header = (f"<!-- imported from legacy notes on "
              f"{datetime.now():%Y-%m-%d %H:%M} -->\n\n")
    save_note(year, client, header + legacy_text)
    if clear_legacy is not None:
        try:
            clear_legacy()
        except Exception:
            pass
    return True


def re_clean_all_notes(progress_cb=None, notes_root=None):
    """Walk every saved .md note and re-run clean_trello_paste against
    the latest cleanup logic. Useful after extending the regexes (like
    the (edited) suffix recognition added in 2026-04) so old notes that
    never got cleaned the first time pick up the fix.

    Subtle: relative timestamps in old notes ("2 hours ago") MUST be
    resolved against the file's mtime, not today's clock, otherwise the
    migration silently rewrites old timestamps as if they were pasted
    today minus 2 hours. The mtime is the closest stable proxy we have
    for "when the user pasted this content".

    Each modified file is backed up to <name>.md.<YYYYMMDD-HHMMSS>.bak so
    repeated migrations don't clobber the prior backup.

    Returns (changed, total). The optional `progress_cb(year, fn, status)`
    fires per file with status ∈ {"unchanged", "updated", "error: <msg>"}.
    """
    root = notes_root if notes_root is not None else _NOTES_ROOT
    if not os.path.isdir(root):
        return 0, 0
    changed = 0
    total = 0
    for year_dir in sorted(os.listdir(root)):
        year_path = os.path.join(root, year_dir)
        if not os.path.isdir(year_path):
            continue
        for fn in sorted(os.listdir(year_path)):
            if not fn.endswith(".md"):
                continue
            total += 1
            path = os.path.join(year_path, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    original = f.read()
            except OSError as ex:
                if progress_cb:
                    progress_cb(year_dir, fn, f"error: {ex}")
                continue
            try:
                ref_time = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                ref_time = datetime.now()
            cleaned = clean_trello_paste(original, now=ref_time)
            if cleaned == original:
                if progress_cb:
                    progress_cb(year_dir, fn, "unchanged")
                continue
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            bak_path = f"{path}.{stamp}.bak"
            try:
                with open(bak_path, "w", encoding="utf-8") as f:
                    f.write(original)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(cleaned)
                changed += 1
                if progress_cb:
                    progress_cb(year_dir, fn, "updated")
            except OSError as ex:
                if progress_cb:
                    progress_cb(year_dir, fn, f"error: {ex}")
    return changed, total


def list_year_folders(base):
    if not os.path.isdir(base):
        return []
    try:
        with os.scandir(base) as it:
            return sorted([e.name for e in it if e.is_dir()],
                          reverse=True)
    except OSError:
        return []


def list_client_folders(base, year_folder):
    p = os.path.join(base, year_folder)
    if not os.path.isdir(p):
        return []
    try:
        with os.scandir(p) as it:
            return sorted([e.name for e in it if e.is_dir()])
    except OSError:
        return []


# ── Panel ───────────────────────────────────────────────────────────────────

class JobNotesApp(ToolPanel):
    TOOL_TITLE = "Job Notes"
    TOOL_AUMID = "Servpro.EMS.JobNotes"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Job Notes")
        self.geometry("1180x740")
        self.minsize(900, 540)
        self.configure(bg=BG)
        if os.path.isfile(_ICON):
            try:
                self.iconbitmap(default=_ICON)
                self.iconbitmap(_ICON)
            except Exception:
                pass

        self._year = None
        self._client = None
        self._dirty = False
        self._loading = False    # suppress modify-handler during programmatic loads
        # Live-audit state for the Expected Files panel.
        # None  → no audit data yet (rows render with neutral • marks)
        # set() → audit ran; rows in the set are missing (✗), others ✓
        self._audit_missing = None
        # Trello-link state. None → unpinned (file-backed mode);
        # str → pinned card_id (live-feed mode). Switched by _load_client
        # after persistence.get_trello_card_id() lookup.
        self._trello_card_id = None      # legacy: first id, kept for some helpers
        self._trello_card_ids = []       # full list of linked card ids
        self._trello_card_cache = {}     # {card_id: card_dict} from latest fetch
        self._trello_active_card_id = None  # which tab is currently shown
        self._trello_last_activity = {}  # {card_id: dateLastActivity}
        self._trello_poll_after_id = None  # tk after-id for the poll loop

        self._build_ui()
        self._refresh_saved_list()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.build_header("SERVPRO  ·  Job Notes",
                          subtitle="Trello dump per client → timeline → expected files",
                          pady=10)

        # Picker bar
        bar = tk.Frame(self, bg=BG, padx=20)
        bar.pack(fill="x", pady=(14, 8))

        ctkh.h2(bar, "Year").pack(side="left")
        self._year_var = tk.StringVar()
        years = list_year_folders(AUDIT_BASE)
        cur_year = str(datetime.now().year)
        cur_year_match = next((y for y in years if cur_year in y), None)
        # Use ttk.Combobox here — the year list can be long and the
        # ttk widget renders a native scrolling popup which CTkComboBox
        # doesn't (CTk's popup is a flat menu that ignores scroll wheels).
        self._year_dd = ttk.Combobox(bar, textvariable=self._year_var,
                                     values=years, width=24, state="readonly",
                                     font=("Segoe UI Variable", 10))
        if cur_year_match:
            self._year_var.set(cur_year_match)
        elif years:
            self._year_var.set(years[0])
        self._year_dd.pack(side="left", padx=(8, 14))
        self._year_dd.bind("<<ComboboxSelected>>", lambda e: self._refresh_clients())

        ctkh.h2(bar, "Client").pack(side="left")
        self._client_var = tk.StringVar()
        self._client_dd = ttk.Combobox(bar, textvariable=self._client_var,
                                       values=[], width=36,
                                       font=("Segoe UI Variable", 10))
        self._client_dd.pack(side="left", padx=(8, 14))
        self._client_dd.bind("<Return>", lambda e: self._load_picked())

        ctkh.btn(bar, "📂  Load", command=self._load_picked,
                 kind="primary", width=110).pack(side="left")
        ctkh.btn(bar, "📥  Export ▾", command=self._export_menu,
                 kind="ghost", width=120).pack(side="right")

        self._refresh_clients()

        # Body: 3-pane PanedWindow so the right column can't get clipped on
        # narrow window widths — drag the dividers to taste, last position
        # persists across sessions.
        body = tk.Frame(self, bg=BG, padx=20)
        body.pack(fill="both", expand=True, pady=(0, 16))

        self._paned = tk.PanedWindow(body, orient="horizontal",
                                      bg=BG, sashrelief="flat",
                                      sashwidth=6, bd=0,
                                      sashpad=0)
        self._paned.pack(fill="both", expand=True)

        # ── Saved-notes sidebar pane ─────────────────────────────────────────
        side = tk.Frame(self._paned, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        tk.Label(side, text="Saved Notes",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=GREEN, fg=WHITE, pady=4).pack(fill="x")

        # Search box — filters by client name (and note body for power users)
        search_row = tk.Frame(side, bg=WHITE, padx=6, pady=4)
        search_row.pack(fill="x")
        self._search_var = tk.StringVar()
        search_entry = tk.Entry(search_row, textvariable=self._search_var,
                                 font=("Segoe UI Variable", 9), relief="flat",
                                 bg=BG, fg=TEXT_DARK,
                                 highlightthickness=1,
                                 highlightbackground=BORDER,
                                 highlightcolor=GREEN)
        search_entry.pack(fill="x", ipady=3)
        # Placeholder behavior — show hint text when empty + unfocused.
        def _placeholder_show():
            if not self._search_var.get():
                search_entry.config(fg=TEXT_MUTED)
                self._search_var.set("Search client or text…")
                self._search_placeholder = True
        def _placeholder_hide(_e=None):
            if getattr(self, "_search_placeholder", False):
                self._search_var.set("")
                search_entry.config(fg=TEXT_DARK)
                self._search_placeholder = False
        def _placeholder_check(_e=None):
            if not self._search_var.get():
                _placeholder_show()
        _placeholder_show()
        search_entry.bind("<FocusIn>", _placeholder_hide)
        search_entry.bind("<FocusOut>", _placeholder_check)

        # Debounce search typing so we don't re-render on every keystroke
        self._search_after_id = None
        def _on_search_change(*_):
            if getattr(self, "_search_placeholder", False):
                return
            if self._search_after_id is not None:
                try:
                    self.after_cancel(self._search_after_id)
                except (tk.TclError, ValueError):
                    pass
            self._search_after_id = self.after(180, self._refresh_saved_list)
        self._search_var.trace_add("write", _on_search_change)

        side_scroll = ScrollableFrame(side, bg=WHITE, canvas_bg=WHITE)
        side_scroll.pack(fill="both", expand=True)
        self._saved_inner = side_scroll.inner
        self._side_scroll = side_scroll

        self._paned.add(side, minsize=160, width=240, stretch="never")

        # ── Editor pane ─────────────────────────────────────────────────────
        ed_card = tk.Frame(self._paned, bg=WHITE,
                           highlightthickness=1, highlightbackground=BORDER)

        ed_hdr = tk.Frame(ed_card, bg=SUCCESS_BG)
        ed_hdr.pack(fill="x")
        self._ed_title = tk.Label(ed_hdr, text="No client loaded",
                                  font=("Segoe UI Variable", 11, "bold"),
                                  bg=SUCCESS_BG, fg=SUCCESS_FG,
                                  padx=10, pady=6)
        self._ed_title.pack(side="left")
        self._ed_meta = tk.Label(ed_hdr, text="",
                                 font=("Segoe UI Variable", 8),
                                 bg=SUCCESS_BG, fg=TEXT_GRAY, padx=10)
        self._ed_meta.pack(side="right")
        # Find-in-note toggle. Lives on the editor header so it's findable
        # without remembering the Ctrl+F shortcut.
        icon_button(ed_hdr, "🔍", fg=SUCCESS_FG, bg=SUCCESS_BG,
                     hover=SUCCESS_HOVER, padx=6, pady=4,
                     font=("Segoe UI Emoji", 11),
                     command=self._toggle_find_bar,
                     tooltip="Find in note (Ctrl+F)"
                     ).pack(side="right", padx=(0, 6))

        # Trello-link controls — hidden until a client is loaded. The
        # status label shows pin state ("📌 Linked" vs "Not linked"); the
        # buttons drive the actions. Building them here keeps the layout
        # stable (no widget-create-on-load shimmy when switching clients).
        self._trello_status_lbl = tk.Label(
            ed_hdr, text="", font=("Segoe UI Variable", 8),
            bg=SUCCESS_BG, fg=TEXT_GRAY, padx=8)
        self._trello_status_lbl.pack(side="right")
        self._trello_refresh_btn = icon_button(
            ed_hdr, "↻", fg=SUCCESS_FG, bg=SUCCESS_BG,
            hover=SUCCESS_HOVER, padx=6, pady=4,
            font=("Segoe UI Variable", 11, "bold"),
            command=self._refresh_from_trello,
            tooltip="Refresh comments from Trello")
        self._trello_open_btn = trello_link_button(
            ed_hdr, command=self._open_trello_card,
            tooltip="Open pinned Trello card")
        self._trello_pin_btn = secondary_button(
            ed_hdr, "📌 Pin to Trello…", padx=8, pady=2,
            font=("Segoe UI Variable", 8),
            command=self._pin_to_trello)
        # Search aliases — alternate names every name lookup will try
        # (SP folder scan, audit folder match, Trello fuzzy match). Goes
        # to the right-side action group so it's visible in both linked
        # and unlinked modes.
        self._aliases_btn = link_button(
            ed_hdr, "🔍 Aliases", padx=8, pady=2,
            font=("Segoe UI Variable", 8, "bold"),
            command=self._open_aliases_dialog)
        # "Add comment" button — appears in linked mode, opens a modal
        # composer dialog so the long-running editor pane isn't cluttered
        # by an always-visible compose box.
        self._trello_comment_btn = done_button(
            ed_hdr, "💬 Add comment", padx=10, pady=2,
            font=("Segoe UI Variable", 8, "bold"),
            command=self._open_compose_dialog)

        # Pack order matters: anchor the save bar to side="bottom" BEFORE
        # ta_box claims space. Otherwise ta_box's Text widget natural height
        # (24 lines) consumes the editor card on short windows and the
        # save bar gets pushed off-screen.
        save_bar = tk.Frame(ed_card, bg=WHITE)
        save_bar.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        self._save_bar = save_bar  # so trello mode can hide/show it
        self._save_btn = ctkh.btn(
            save_bar, "💾  Save", command=self._save_current,
            kind="primary", width=110, state="disabled")
        self._save_btn.pack(side="left")
        self._dirty_lbl = ctkh.ctk.CTkLabel(
            save_bar, text="", font=ctkh.font(9),
            text_color=TEXT_GRAY, fg_color=WHITE)
        self._dirty_lbl.pack(side="left", padx=(12, 0))
        # Open in Notepad is rare (quick edit in an external editor) —
        # tucked into ⋯ so the save bar is just save + dirty indicator.
        notes_more = ctkh.MoreMenu(save_bar, label="⋯", width=36)
        notes_more.add("Open in Notepad", icon="📁",
                       command=self._open_in_notepad)
        notes_more.button.pack(side="right")

        # Find-in-note bar — slim row above the textarea. Hidden until the
        # user opens it (Ctrl+F or the 🔍 button on the editor header).
        # Lives between save_bar (already side=bottom) and ta_box so it
        # naturally sits just above the editor.
        self._find_bar = tk.Frame(ed_card, bg=BG,
                                   highlightbackground=BORDER,
                                   highlightthickness=1)
        # Don't pack yet — _toggle_find_bar handles show/hide.
        self._find_var = tk.StringVar()
        self._find_entry = tk.Entry(
            self._find_bar, textvariable=self._find_var,
            font=("Segoe UI Variable", 9), relief="flat",
            bg=WHITE, fg=TEXT_DARK,
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=GREEN)
        self._find_entry.pack(side="left", fill="x", expand=True,
                              padx=(8, 4), pady=4, ipady=2)
        icon_button(self._find_bar, "↑", fg=TEXT_DARK, bg=BG,
                     hover=SUCCESS_HOVER, padx=6, pady=4,
                     font=("Segoe UI Variable", 9, "bold"),
                     command=lambda: self._find_step(-1)).pack(side="left")
        icon_button(self._find_bar, "↓", fg=TEXT_DARK, bg=BG,
                     hover=SUCCESS_HOVER, padx=6, pady=4,
                     font=("Segoe UI Variable", 9, "bold"),
                     command=lambda: self._find_step(+1)).pack(side="left")
        self._find_count = tk.Label(self._find_bar, text="",
                                     font=("Segoe UI Variable", 8),
                                     bg=BG, fg=TEXT_GRAY)
        self._find_count.pack(side="left", padx=(8, 4))
        icon_button(self._find_bar, "✕", fg=TEXT_GRAY, bg=BG,
                     hover=SUCCESS_HOVER, padx=6, pady=4,
                     command=self._toggle_find_bar
                     ).pack(side="right", padx=4)
        # Search-in-note state. _find_matches: list of (start, end) Tk
        # indexes for every hit; _find_current: index into that list.
        self._find_matches = []
        self._find_current = -1
        self._find_after_id = None
        # Debounced re-scan as the user types — fast for short notes,
        # avoids re-tagging on every keystroke for long Trello dumps.
        self._find_var.trace_add("write", self._on_find_var_change)
        # Enter = next, Shift+Enter = prev, Esc = close.
        self._find_entry.bind("<Return>", lambda _e: self._find_step(+1))
        self._find_entry.bind("<Shift-Return>", lambda _e: self._find_step(-1))
        self._find_entry.bind("<Escape>", lambda _e: self._toggle_find_bar(False))

        # Tab bar — only visible when the client is linked to 2+ Trello
        # cards. One button per card showing "Board · Lane"; the active
        # tab gets a distinct fill so the user can see which card the
        # buffer below belongs to. Switching tabs swaps the textarea
        # content (cached so toggling between cards is instant).
        self._trello_tab_bar = tk.Frame(
            ed_card, bg=BG,
            highlightbackground=BORDER, highlightthickness=1)
        # Pack lazily in _rebuild_trello_tabs so single-card mode keeps
        # the existing chrome-free layout.

        ta_box = tk.Frame(ed_card, bg=WHITE)
        ta_box.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        self._textarea = tk.Text(ta_box, font=("Consolas", 10),
                                 wrap="word", relief="flat",
                                 bg=WHITE, fg=TEXT_DARK,
                                 padx=8, pady=6, undo=True,
                                 height=8,  # min height; expand fills the rest
                                 state="disabled")
        ta_sb = tk.Scrollbar(ta_box, command=self._textarea.yview)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(ta_sb)
        except Exception:
            pass
        self._textarea.configure(yscrollcommand=ta_sb.set)
        ta_sb.pack(side="right", fill="y")
        self._textarea.pack(side="left", fill="both", expand=True)
        self._textarea.bind("<<Modified>>", self._on_text_modified)
        # Trello-paste cleanup — when the clipboard has a Trello comment
        # dump, swap the default paste with the normalized version. Plain
        # text falls through unchanged so generic pastes still work.
        self._textarea.bind("<<Paste>>", self._on_paste)
        # Ctrl+F opens the find bar from the editor. Bound only on the
        # textarea (not bind_all) so it doesn't steal Ctrl+F from other
        # panels when this one is hidden.
        self._textarea.bind("<Control-f>",
                             lambda _e: (self._toggle_find_bar(True), "break")[1])
        self._configure_message_tags()
        self._configure_find_tags()
        self._configure_md_tags()

        self._paned.add(ed_card, minsize=320, stretch="always")

        # ── Right pane — combined Timeline + Expected Files (scrollable) ─────
        right = tk.Frame(self._paned, bg=BG)
        right_scroll = ScrollableFrame(right, bg=BG)
        right_scroll.pack(fill="both", expand=True)
        right_inner       = right_scroll.inner
        self._right_scroll = right_scroll

        tl_card = tk.Frame(right_inner, bg=WHITE,
                           highlightthickness=1, highlightbackground=BORDER)
        tl_card.pack(fill="x")
        tk.Label(tl_card, text="Timeline",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=GREEN, fg=WHITE, pady=4).pack(fill="x")
        self._timeline_inner = tk.Frame(tl_card, bg=WHITE, padx=12, pady=10)
        self._timeline_inner.pack(fill="x")

        ef_card = tk.Frame(right_inner, bg=WHITE,
                           highlightthickness=1, highlightbackground=BORDER)
        ef_card.pack(fill="x", pady=(10, 0))
        tk.Label(ef_card, text="Expected Files",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=GREEN, fg=WHITE, pady=4).pack(fill="x")
        self._expected_inner = tk.Frame(ef_card, bg=WHITE, padx=12, pady=10)
        self._expected_inner.pack(fill="x")

        self._paned.add(right, minsize=180, width=280, stretch="never")

        # Restore last sash positions and persist on drag
        self._paned_key = "job_notes:body"
        self._restore_sash()
        self._paned.bind("<ButtonRelease-1>", lambda e: self._save_sash())

        # Pre-build timeline + expected-files rows once. Re-rendering on
        # every keystroke used to destroy/recreate ~10 widgets per refresh,
        # which read as visible jitter. Now we just pack/unpack and reconfig.
        self._build_timeline_widgets()
        self._build_expected_widgets()
        self._render_timeline([])
        self._render_expected([])
        self._refresh_views_after_id = None

    # ── Pane sash persistence ───────────────────────────────────────────────
    def _restore_sash(self):
        positions = persistence.get_sash_positions(self._paned_key)
        if not positions:
            return
        # Defer until widget is mapped — sash_place is a no-op before that.
        def _apply():
            try:
                for idx, x in enumerate(positions):
                    self._paned.sash_place(idx, x, 1)
            except tk.TclError:
                pass
        self.after(50, _apply)

    def _save_sash(self):
        try:
            n_sashes = len(self._paned.panes()) - 1
            xs = []
            for i in range(n_sashes):
                coord = self._paned.sash_coord(i)
                if coord:
                    xs.append(int(coord[0]))
            if xs:
                persistence.set_sash_positions(self._paned_key, xs)
        except tk.TclError:
            pass

    # ── Refresh helpers ─────────────────────────────────────────────────────
    def _refresh_clients(self):
        year = self._year_var.get()
        self._client_dd["values"] = list_client_folders(AUDIT_BASE, year) if year else []

    def _refresh_saved_list(self):
        self._search_after_id = None
        for w in self._saved_inner.winfo_children():
            w.destroy()
        notes = list_saved_notes()
        if not notes:
            tk.Label(self._saved_inner,
                     text="No notes yet — pick a client above and start typing.",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     wraplength=210, justify="left",
                     padx=10, pady=10).pack(anchor="w")
            return

        # Apply search filter — empty / placeholder query means show all
        query = ""
        if not getattr(self, "_search_placeholder", False):
            query = (getattr(self, "_search_var", None)
                     and self._search_var.get().strip().lower()) or ""

        if query:
            filtered = []
            for year, client, mtime in notes:
                if query in client.lower() or query in str(year).lower():
                    filtered.append((year, client, mtime))
                    continue
                # Power-user: also grep the note body for the query
                try:
                    txt = load_note(year, client).lower()
                    if query in txt:
                        filtered.append((year, client, mtime))
                except Exception:
                    pass
            notes = filtered

        if not notes:
            tk.Label(self._saved_inner,
                     text=f"No matches for '{query}'.",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     wraplength=210, justify="left",
                     padx=10, pady=10).pack(anchor="w")
            return

        for year, client, mtime in notes:
            is_current = (str(year) == str(self._year) and client == self._client)
            row_bg = "#E8F5EE" if is_current else WHITE
            row = tk.Frame(self._saved_inner, bg=row_bg, padx=10, pady=6,
                           cursor="hand2")
            row.pack(fill="x")
            lbl_top = tk.Label(row, text=client,
                               font=("Segoe UI Variable", 9,
                                     "bold" if is_current else "normal"),
                               bg=row_bg,
                               fg=GREEN_DARK if is_current else TEXT_DARK,
                               anchor="w", cursor="hand2")
            lbl_top.pack(fill="x")
            try:
                date_s = datetime.fromtimestamp(mtime).strftime("%b %d")
            except Exception:
                date_s = ""
            lbl_bot = tk.Label(row, text=f"{year}  ·  edited {date_s}",
                               font=("Segoe UI Variable", 7),
                               bg=row_bg, fg=TEXT_GRAY,
                               anchor="w", cursor="hand2")
            lbl_bot.pack(fill="x")
            tk.Frame(self._saved_inner, bg=BORDER, height=1).pack(fill="x")
            for w in (row, lbl_top, lbl_bot):
                w.bind("<Button-1>",
                       lambda e, y=year, c=client: self._load_client(y, c))

    # ── Load / save ─────────────────────────────────────────────────────────
    def _load_picked(self):
        year = self._year_var.get().strip()
        client = self._client_var.get().strip()
        if not year or not client:
            messagebox.showinfo("Pick a client",
                                "Choose a year and client folder first.",
                                parent=self)
            return
        self._load_client(year, client)

    def _load_client(self, year, client):
        if self._dirty and not messagebox.askyesno(
                "Unsaved changes",
                f"Discard unsaved changes for {self._client}?",
                parent=self):
            return
        self._year = year
        self._client = client

        # Decide source: pinned Trello card(s) → live feed; else local .md.
        # The pin lookup is in-process cached so this is essentially free.
        self._trello_card_ids = persistence.get_trello_card_ids(client)
        self._trello_card_id = (self._trello_card_ids[0]
                                if self._trello_card_ids else None)
        # Reset active selection so a fresh client load doesn't carry
        # the prior client's active card (which won't be in the new
        # cache anyway).
        self._trello_active_card_id = None
        self._trello_card_cache = {}
        loaded_from_trello = False
        if self._trello_card_ids:
            text, ok = self._fetch_trello_text(self._trello_card_ids)
            loaded_from_trello = ok
        if not loaded_from_trello:
            text = load_note(year, client)
        self._loading = True
        try:
            self._textarea.config(state="normal")
            self._textarea.delete("1.0", "end")
            self._textarea.insert("1.0", text)
            self._textarea.edit_modified(False)
        finally:
            self._loading = False
        self._dirty = False
        self._save_btn.configure(state="normal")
        self._dirty_lbl.configure(text="")
        self._ed_title.config(text=f"{client}  ·  {year}")
        if loaded_from_trello:
            # Live-feed mode: meta label shows when we last refreshed,
            # not the .md mtime (which is irrelevant in this mode).
            self._ed_meta.config(
                text=f"refreshed {datetime.now().strftime('%b %d, %Y %I:%M %p')}")
        else:
            p = _notes_path(year, client)
            if os.path.isfile(p):
                mtime = datetime.fromtimestamp(os.path.getmtime(p))
                self._ed_meta.config(text=f"saved {mtime.strftime('%b %d, %Y %I:%M %p')}")
            else:
                self._ed_meta.config(text="(not saved yet)")
        self._update_trello_toolbar(loaded_from_trello)
        # Show/hide the per-card tab bar based on how many cards we
        # successfully fetched (rebuild always — empty case hides it).
        self._rebuild_trello_tabs()
        # Poll the card while it's open. Cancel first in case we just
        # switched away from another linked client.
        self._cancel_trello_poll()
        if loaded_from_trello:
            self._start_trello_poll()
        # Re-tag the buffer so already-saved Trello dumps render as cards
        # and any markdown markers (#, **, *, `, -) get styled in place.
        self._apply_message_tags()
        self._apply_info_tags()
        self._apply_md_styles()
        # If the find bar was open with a query, re-run against the new
        # buffer; stale highlights from the prior client would mislead.
        if self._find_bar.winfo_manager() and self._find_var.get():
            self._run_find()
        else:
            self._clear_find_tags()
        # Audit runs against the loaded client + currently parsed stages.
        # Order matters: parse stages first (via _do_refresh_views), then
        # the audit picks them up to know which photo categories to check.
        self._do_refresh_views()
        self._refresh_audit_status()
        # Re-render Expected Files now that the audit set is populated so
        # the ✓/✗ marks show up on the rows we just packed.
        text = self._textarea.get("1.0", "end-1c")
        self._render_expected(expected_files(parse_stages(text)))
        self._refresh_saved_list()

    def _configure_message_tags(self):
        """Set up the Text widget tags used to render each Trello comment
        as a distinct card. Header lines get a colored band and the body
        gets a tinted background so messages sit visually apart."""
        self._textarea.tag_configure(
            "msg_header",
            background=SUCCESS_HOVER, foreground=SUCCESS_FG,
            font=("Segoe UI Variable", 10, "bold"),
            spacing1=12, spacing3=4,
            lmargin1=8, lmargin2=8, rmargin=8,
        )
        # Body background sits a tick darker than the panel BG so the
        # message card stays visible against the editor surface.
        self._textarea.tag_configure(
            "msg_body",
            background=SUCCESS_BG, foreground=TEXT_DARK,
            lmargin1=14, lmargin2=14, rmargin=14,
            spacing3=6,
        )
        # Header tag should win when both apply (the body region begins
        # immediately after the header line — overlap is just the boundary
        # newline, but explicit raise keeps the styling stable).
        self._textarea.tag_raise("msg_header")

        # Job-info / Checklist sections — a distinct card style separate
        # from the green message-card palette so the structural Trello
        # data (carrier, claim, milestones) reads as reference info, not
        # as someone's comment. Amber/cream tones pair with the green
        # message cards without competing.
        self._textarea.tag_configure(
            "info_header",
            background=WARN_HOVER, foreground=WARN_FG,
            font=("Segoe UI Variable", 10, "bold"),
            spacing1=14, spacing3=4,
            lmargin1=8, lmargin2=8, rmargin=8,
        )
        self._textarea.tag_configure(
            "info_body",
            background=WARN_BG, foreground=TEXT_DARK,
            lmargin1=14, lmargin2=14, rmargin=14,
            spacing3=6,
        )
        self._textarea.tag_raise("info_header")

    def _apply_message_tags(self):
        """Scan the buffer for `Author · Date` headers and tag each
        message so the Text widget renders them as separate cards.
        Cheap (one regex pass) so it's safe to call after every load,
        paste, or debounced edit."""
        self._textarea.tag_remove("msg_header", "1.0", "end")
        self._textarea.tag_remove("msg_body", "1.0", "end")
        text = self._textarea.get("1.0", "end-1c")
        if not text:
            return
        headers = list(_RENDERED_HEADER_RE.finditer(text))
        if not headers:
            return
        for i, m in enumerate(headers):
            self._textarea.tag_add("msg_header",
                                    f"1.0 + {m.start()}c",
                                    f"1.0 + {m.end()}c")
            body_start = m.end() + 1  # skip the newline ending the header line
            body_end = (headers[i + 1].start()
                        if i + 1 < len(headers) else len(text))
            if body_end > body_start:
                self._textarea.tag_add("msg_body",
                                        f"1.0 + {body_start}c",
                                        f"1.0 + {body_end}c")

    # Section markers emitted by trello_client.format_activity_feed —
    # any `**JOB INFO**` / `**CHECKLISTS**` / `**CARD: ...**` line at the
    # start of its paragraph denotes a structured info block. We tag the
    # header line with `info_header` and everything after it (until the
    # next section header, the next `Author · Date` message header, or a
    # `---` horizontal break) with `info_body`.
    # ACTIVITY is included so the styling pass can recognize where the
    # info blocks STOP — the `_apply_info_tags` skip below avoids tagging
    # the activity stream itself with info colors.
    _INFO_SECTION_RE = re.compile(
        r"^\*\*(JOB INFO|CHECKLISTS|ACTIVITY|CARD: [^*\n]+)\*\*\s*$",
        re.MULTILINE)

    def _apply_info_tags(self):
        """Tag JOB INFO + CHECKLISTS sections with the info-card palette
        so they read as reference blocks, distinct from the green
        message-card stream. Idempotent — safe to call after every
        load/refresh/edit."""
        self._textarea.tag_remove("info_header", "1.0", "end")
        self._textarea.tag_remove("info_body", "1.0", "end")
        text = self._textarea.get("1.0", "end-1c")
        if not text:
            return
        sections = list(self._INFO_SECTION_RE.finditer(text))
        if not sections:
            return
        # Author · Date header positions form the other "stop boundaries"
        # for an info-body region — once the activity stream begins, we
        # want the message-card styling to take over instead.
        msg_starts = [m.start() for m in _RENDERED_HEADER_RE.finditer(text)]
        for i, m in enumerate(sections):
            label = m.group(1)
            # ACTIVITY is the message-card section — skip styling its
            # header (and don't extend a body block into the comment
            # stream that follows).
            if label == "ACTIVITY":
                continue
            # CARD: <name> banners introduce a per-card info block in
            # multi-card mode; they share the same amber palette since
            # they're part of the structured-info family of sections.
            self._textarea.tag_add("info_header",
                                   f"1.0 + {m.start()}c",
                                   f"1.0 + {m.end()}c")
            body_start = m.end() + 1   # past the newline ending header
            # End at: next info section, next message header, or buffer end.
            stops = [s.start() for s in sections[i + 1:]]
            stops += [s for s in msg_starts if s > body_start]
            stops.append(len(text))
            body_end = min(stops)
            # Trim trailing horizontal-break delimiter ("---") so the
            # info card stops above it rather than swallowing the divider.
            chunk = text[body_start:body_end].rstrip()
            if chunk.endswith("---"):
                chunk = chunk[:-3].rstrip()
            body_end = body_start + len(chunk)
            if body_end > body_start:
                self._textarea.tag_add("info_body",
                                       f"1.0 + {body_start}c",
                                       f"1.0 + {body_end}c")

    # ── Lightweight markdown styling ───────────────────────────────────────
    def _configure_md_tags(self):
        """Configure tags used to render headers, bold, italic, code, and
        bullets visually. Markers (#, **, *, `, leading -) get hidden via
        the md_marker tag's elide attribute so the user sees the styled
        result without the punctuation noise — same idea as Notion or the
        GitHub markdown preview, just done in-place inside the Text widget."""
        # Heading sizes step down so visual hierarchy is obvious. Segoe UI
        # for headings (the body is Consolas) so they break out of the
        # mono grid the way they do in any markdown renderer.
        self._textarea.tag_configure(
            "md_h1", font=("Segoe UI Variable", 16, "bold"),
            foreground=GREEN_DARK, spacing1=10, spacing3=4)
        self._textarea.tag_configure(
            "md_h2", font=("Fraunces", 15, "bold"),
            foreground=GREEN_DARK, spacing1=8, spacing3=3)
        self._textarea.tag_configure(
            "md_h3", font=("Segoe UI Variable", 11, "bold"),
            foreground=TEXT_DARK, spacing1=6, spacing3=2)
        self._textarea.tag_configure(
            "md_bold", font=("Consolas", 10, "bold"))
        self._textarea.tag_configure(
            "md_italic", font=("Consolas", 10, "italic"))
        self._textarea.tag_configure(
            "md_code", font=("Consolas", 10),
            background=SURFACE_2, foreground=DANGER_FG)
        # Bullet rows get a left margin so the dash hangs into a gutter and
        # wrapped lines line up under the text rather than the marker.
        self._textarea.tag_configure(
            "md_bullet", lmargin1=8, lmargin2=24)
        # Marker tag: hide via elide. Tk's Text.search by default ignores
        # elided ranges, so users searching for "**" won't find them — fine,
        # they're not meant to be visible content.
        self._textarea.tag_configure("md_marker", elide=True)
        # Find-bar highlights need to win over markdown styling, and the
        # message-card backgrounds should win over plain body. Raise tags
        # in the order: msg_body < md_* < msg_header < find_match <
        # find_current.
        for t in ("md_h1", "md_h2", "md_h3", "md_bold", "md_italic",
                   "md_code", "md_bullet", "md_marker"):
            self._textarea.tag_raise(t, "msg_body")
        self._textarea.tag_raise("msg_header")
        self._textarea.tag_raise("find_match")
        self._textarea.tag_raise("find_current")

    def _apply_md_styles(self):
        """Re-tag the buffer for markdown markers. Cheap enough (regex over
        the whole buffer) to run after every load, paste, or debounced
        edit — same call sites as _apply_message_tags."""
        for t in ("md_h1", "md_h2", "md_h3", "md_bold", "md_italic",
                   "md_code", "md_bullet", "md_marker"):
            self._textarea.tag_remove(t, "1.0", "end")
        text = self._textarea.get("1.0", "end-1c")
        if not text:
            return

        def _idx(offset):
            return f"1.0 + {offset}c"

        # Headers — apply the level tag to the whole line, hide the
        # leading "#"/"## "/"### " markers so the user sees just the title.
        for m in _MD_HEADER_RE.finditer(text):
            level = len(m.group(1))
            tag = {1: "md_h1", 2: "md_h2", 3: "md_h3"}[level]
            line_start = m.start()
            line_end = m.end()
            self._textarea.tag_add(tag, _idx(line_start), _idx(line_end))
            # Marker covers the "#"s + the single space after.
            marker_end = line_start + level + 1
            self._textarea.tag_add("md_marker",
                                   _idx(line_start), _idx(marker_end))

        # Bold — `**text**`. Style the inner content, hide the asterisks.
        for m in _MD_BOLD_RE.finditer(text):
            self._textarea.tag_add("md_bold",
                                   _idx(m.start(1)), _idx(m.end(1)))
            self._textarea.tag_add("md_marker",
                                   _idx(m.start()), _idx(m.start(1)))
            self._textarea.tag_add("md_marker",
                                   _idx(m.end(1)), _idx(m.end()))

        # Italic — `*text*`. Same idea but with single asterisks. The
        # negative-look-around in the regex keeps it from matching parts
        # of `**bold**` or words containing asterisks.
        for m in _MD_ITALIC_RE.finditer(text):
            self._textarea.tag_add("md_italic",
                                   _idx(m.start(1)), _idx(m.end(1)))
            self._textarea.tag_add("md_marker",
                                   _idx(m.start()), _idx(m.start(1)))
            self._textarea.tag_add("md_marker",
                                   _idx(m.end(1)), _idx(m.end()))

        # Inline code — `code`. Backticks elided.
        for m in _MD_CODE_RE.finditer(text):
            self._textarea.tag_add("md_code",
                                   _idx(m.start(1)), _idx(m.end(1)))
            self._textarea.tag_add("md_marker",
                                   _idx(m.start()), _idx(m.start(1)))
            self._textarea.tag_add("md_marker",
                                   _idx(m.end(1)), _idx(m.end()))

        # Bullets — leading "- " or "* " replaced visually with a real
        # bullet glyph. We can't actually substitute characters in the
        # buffer (would mess with .md storage), so the marker tag hides
        # the original "-"/"*" + trailing space and a bullet-prefixed
        # margin makes the line look indented like a list. We DO insert
        # the bullet glyph as a window? Simpler: just keep the dash but
        # hide it; rely on the indent + spacing to suggest list-ness.
        # Most markdown renderers people are used to (GitHub, Slack)
        # don't actually replace the dash either.
        for m in _MD_BULLET_RE.finditer(text):
            line_start = m.start()
            line_end = m.end()
            self._textarea.tag_add("md_bullet",
                                   _idx(line_start), _idx(line_end))

    # ── Find in note ────────────────────────────────────────────────────────
    def _configure_find_tags(self):
        """Tags used to highlight find-in-note matches. `find_match` is the
        soft-yellow band on every hit; `find_current` is the deeper orange
        on whichever hit ↑/↓ landed on. Raised above the message tags so
        the highlight wins visually over the green card backgrounds."""
        self._textarea.tag_configure(
            "find_match", background="#FFF59D", foreground="#1C1815")
        self._textarea.tag_configure(
            "find_current", background="#FFB74D", foreground="#1C1815")
        self._textarea.tag_raise("find_match")
        self._textarea.tag_raise("find_current")

    def _toggle_find_bar(self, force=None):
        """Show/hide the find bar. `force=True` shows, `False` hides;
        passing nothing toggles based on current state."""
        # info() returns {} when the widget isn't packed, truthy dict otherwise.
        currently_shown = bool(self._find_bar.winfo_manager())
        target = (not currently_shown) if force is None else bool(force)
        if target:
            # Pack above ta_box so it sits between the header and editor.
            self._find_bar.pack(side="top", fill="x", padx=10, pady=(4, 0),
                                before=self._textarea.master)
            self._find_entry.focus_set()
            self._find_entry.select_range(0, "end")
            # Re-run search in case text changed while bar was hidden.
            self._run_find()
        else:
            self._find_bar.pack_forget()
            self._clear_find_tags()
            self._find_matches = []
            self._find_current = -1
            self._find_count.config(text="")
            # Return focus to the editor so typing continues to land there.
            try:
                self._textarea.focus_set()
            except tk.TclError:
                pass

    def _on_find_var_change(self, *_):
        """Debounced re-scan as the user types — 120ms idle window keeps
        the highlight responsive without re-tagging on every keystroke
        for long Trello dumps."""
        if self._find_after_id is not None:
            try:
                self.after_cancel(self._find_after_id)
            except (tk.TclError, ValueError):
                pass
        self._find_after_id = self.after(120, self._run_find)

    def _clear_find_tags(self):
        self._textarea.tag_remove("find_match", "1.0", "end")
        self._textarea.tag_remove("find_current", "1.0", "end")

    def _run_find(self):
        """Scan the buffer for the current query and tag every hit. The
        first hit (or the one nearest the insert cursor) becomes current."""
        self._find_after_id = None
        self._clear_find_tags()
        self._find_matches = []
        self._find_current = -1
        query = self._find_var.get()
        if not query:
            self._find_count.config(text="")
            return
        # Tk's Text.search returns one hit at a time; nocase=1 matches
        # case-insensitively the way users expect from a find bar.
        idx = "1.0"
        while True:
            count_var = tk.IntVar(master=self._textarea)
            hit = self._textarea.search(query, idx, stopindex="end",
                                         nocase=1, count=count_var)
            if not hit:
                break
            length = count_var.get() or len(query)
            end = f"{hit}+{length}c"
            self._textarea.tag_add("find_match", hit, end)
            self._find_matches.append((hit, end))
            idx = end
        if not self._find_matches:
            self._find_count.config(text="no matches", fg=FLAG_RED)
            return
        # Pick the match nearest (or after) the insert cursor so jumping
        # in mid-document feels natural.
        try:
            cursor = self._textarea.index("insert")
        except tk.TclError:
            cursor = "1.0"
        start_idx = 0
        for i, (hit, _end) in enumerate(self._find_matches):
            if self._textarea.compare(hit, ">=", cursor):
                start_idx = i
                break
        self._find_current = start_idx
        self._highlight_current_match()

    def _highlight_current_match(self):
        """Promote the active match to the deeper-orange tag and scroll
        it into view. Called after _run_find and after each ↑/↓ step."""
        self._textarea.tag_remove("find_current", "1.0", "end")
        if not self._find_matches:
            return
        hit, end = self._find_matches[self._find_current]
        self._textarea.tag_add("find_current", hit, end)
        self._textarea.see(hit)
        total = len(self._find_matches)
        self._find_count.config(
            text=f"{self._find_current + 1} of {total}",
            fg=TEXT_GRAY)

    def _find_step(self, direction):
        """Move ↑ (-1) or ↓ (+1) through the match list with wrap-around."""
        if not self._find_matches:
            # Re-run in case the user typed a query but hasn't paused
            # long enough for the debounce to fire.
            self._run_find()
            if not self._find_matches:
                return "break"
        n = len(self._find_matches)
        self._find_current = (self._find_current + direction) % n
        self._highlight_current_match()
        return "break"

    def _on_text_modified(self, event=None):
        if self._loading:
            return
        if self._textarea.edit_modified():
            self._dirty = True
            self._dirty_lbl.configure(text="• unsaved changes", text_color="#B58B00")
            self._textarea.edit_modified(False)
            self._refresh_views()
            # Find results go stale once the text changes — re-run if the
            # bar is open so the highlights track edits.
            if self._find_bar.winfo_manager() and self._find_var.get():
                self._on_find_var_change()

    def _on_paste(self, event=None):
        """Intercept Ctrl+V / Edit→Paste so a Trello dump in the clipboard
        gets normalized before it lands in the editor. Non-Trello text is
        left alone (clean_trello_paste returns the input unchanged), in
        which case we let Tk's default paste handler run."""
        try:
            clip = self._textarea.clipboard_get()
        except tk.TclError:
            return None
        cleaned = clean_trello_paste(clip)
        if cleaned == clip:
            return None  # plain paste — let the default class binding run
        # Replace any active selection so the cleaned text overwrites it,
        # matching Tk's default paste behavior.
        try:
            self._textarea.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        self._textarea.insert("insert", cleaned)
        self._textarea.see("insert")
        # Re-tag immediately so the inserted comments get the card styling
        # and any markdown markers in the cleaned content render styled.
        self._apply_message_tags()
        self._apply_info_tags()
        self._apply_md_styles()
        return "break"

    def _refresh_views(self):
        # Debounced — coalesce multiple keystrokes into one parse pass after
        # 200ms of idle. parse_stages itself is cheap, but skipping the call
        # while the user is actively typing keeps the timeline visually still.
        if self._refresh_views_after_id is not None:
            try:
                self.after_cancel(self._refresh_views_after_id)
            except (tk.TclError, ValueError):
                pass
        self._refresh_views_after_id = self.after(200, self._do_refresh_views)

    def _do_refresh_views(self):
        self._refresh_views_after_id = None
        text = self._textarea.get("1.0", "end-1c")
        stages = parse_stages(text)
        self._render_timeline(stages)
        self._render_expected(expected_files(stages))
        # Re-tag too so card styling + markdown styling stay in sync with
        # edits — same 200ms debounce as the timeline parse so we don't
        # thrash on every key.
        self._apply_message_tags()
        self._apply_info_tags()
        self._apply_md_styles()

    # ── Trello live-feed wiring ─────────────────────────────────────────────
    def _fetch_trello_text(self, card_ids):
        """Fetch every linked card into the cache, return (text, ok)
        where text is the *active card's* feed (each tab is independent).
        Accepts either a single id (back-compat) or a list.

        On failure (network/auth/all-cards-missing) returns ('', False)
        so the caller falls back to local notes — never blocks the user
        from seeing something."""
        if isinstance(card_ids, str):
            card_ids = [card_ids]
        if not card_ids:
            return "", False
        cache = {}
        last_activity = {}
        for cid in card_ids:
            try:
                card = trello_client.get_card(cid)
            except Exception as ex:
                show_toast(self, f"Trello: {ex}", kind="error")
                continue
            if not card:
                # Skip silently — picker is the right place to surface a
                # stale pin (user can re-link).
                continue
            cache[cid] = card
            last_activity[cid] = card.get("dateLastActivity")
        if not cache:
            show_toast(self,
                       "No linked Trello cards could be fetched",
                       kind="error")
            return "", False
        self._trello_card_cache = cache
        self._trello_last_activity = last_activity
        # Pick a sensible active card: keep current selection if it's
        # still in the cache, else fall back to the first id we got.
        if (self._trello_active_card_id not in cache):
            # Preserve the persisted ORDER (card_ids is the list from
            # persistence). First successfully-fetched id wins.
            self._trello_active_card_id = next(
                (cid for cid in card_ids if cid in cache),
                next(iter(cache)))
        active_card = cache[self._trello_active_card_id]
        if active_card.get("closed"):
            show_toast(self,
                       "Trello card is archived — showing as read-only",
                       kind="info")
        lane = trello_client.get_lane_name(
            active_card.get("idBoard"), active_card.get("idList"))
        text = trello_client.format_activity_feed(
            active_card, lane_name=lane)
        return text, True

    def _swap_to_trello_card(self, card_id):
        """Tab-bar handler — switch the textarea to a different cached
        card without re-fetching. Re-applies tags so the styling is
        consistent across tabs."""
        if card_id not in self._trello_card_cache:
            return
        if card_id == self._trello_active_card_id:
            return  # already showing
        self._trello_active_card_id = card_id
        card = self._trello_card_cache[card_id]
        lane = trello_client.get_lane_name(
            card.get("idBoard"), card.get("idList"))
        text = trello_client.format_activity_feed(card, lane_name=lane)
        self._loading = True
        try:
            self._textarea.config(state="normal")
            self._textarea.delete("1.0", "end")
            self._textarea.insert("1.0", text)
            self._textarea.edit_modified(False)
            self._textarea.config(state="disabled")  # back to read-only
        finally:
            self._loading = False
        self._apply_message_tags()
        self._apply_info_tags()
        self._apply_md_styles()
        self._do_refresh_views()
        self._rebuild_trello_tabs()  # update active-tab styling

    def _rebuild_trello_tabs(self):
        """Re-render the tab-bar buttons based on the current cache and
        active selection. Hides the bar entirely when 0–1 cards are
        linked (no value showing a single tab)."""
        for w in self._trello_tab_bar.winfo_children():
            w.destroy()
        cards = [self._trello_card_cache.get(cid)
                 for cid in self._trello_card_ids
                 if cid in self._trello_card_cache]
        if len(cards) < 2:
            try:
                self._trello_tab_bar.pack_forget()
            except tk.TclError:
                pass
            return
        try:
            self._trello_tab_bar.pack(fill="x", padx=10, pady=(2, 0))
        except tk.TclError:
            pass
        tk.Label(self._trello_tab_bar, text="Trello:",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=BG, fg=SUCCESS_FG,
                 padx=8).pack(side="left", pady=2)
        for card in cards:
            cid = card.get("id") or card.get("shortLink")
            # Show "Board · Lane" so the user can tell which board they're
            # looking at without expanding into the buffer below.
            board_name = self._board_name_for(card.get("idBoard"))
            lane = trello_client.get_lane_name(
                card.get("idBoard"), card.get("idList"))
            label_bits = [board_name or "?"]
            if lane:
                label_bits.append(lane)
            label = "  ·  ".join(label_bits)
            is_active = (cid == self._trello_active_card_id)
            btn = tk.Button(
                self._trello_tab_bar, text=label,
                font=("Segoe UI Variable", 8, "bold" if is_active else "normal"),
                bg=GREEN if is_active else WHITE,
                fg=WHITE if is_active else TEXT_DARK,
                activebackground=GREEN_DARK if is_active else "#E8F5EE",
                activeforeground=WHITE if is_active else TEXT_DARK,
                relief="flat" if is_active else "solid",
                bd=0 if is_active else 1,
                padx=10, pady=3, cursor="hand2",
                command=lambda _cid=cid: self._swap_to_trello_card(_cid))
            btn.pack(side="left", padx=(2, 0), pady=2)

    def _board_name_for(self, board_id):
        """Resolve a board id to its display name via the cached
        list_boards lookup. Keeps the tab bar from showing raw ids when
        the board is in the configured workspace."""
        if not board_id:
            return ""
        try:
            for b in trello_client.list_boards():
                if b.get("id") == board_id:
                    return b.get("name") or ""
        except Exception:
            pass
        return ""

    def _update_trello_toolbar(self, linked):
        """Show/hide the Trello buttons + textarea state based on link
        state. Called from _load_client after the source decision is
        made.

        Linked mode: textarea is read-only (live feed, no in-buffer
        edits), Save bar is hidden, "Add comment" button is visible.
        Unlinked mode: textarea editable (local .md notes), Save bar
        visible, no Trello buttons — preserves the prior file-backed
        behavior for clients without a Trello card."""
        # Clear prior layout — pack each call so toggle is clean.
        for w in (self._trello_refresh_btn, self._trello_open_btn,
                  self._trello_pin_btn, self._trello_comment_btn,
                  self._aliases_btn):
            try:
                w.pack_forget()
            except tk.TclError:
                pass
        # Aliases button is always visible when a client is loaded —
        # alias management is independent of Trello pin state.
        if self._client:
            self._aliases_btn.pack(side="right", padx=(0, 2))
        if linked:
            self._trello_status_lbl.config(
                text="📌 Linked to Trello", fg=GREEN_DARK)
            self._trello_comment_btn.pack(side="right", padx=(6, 2))
            self._trello_refresh_btn.pack(side="right", padx=(0, 2))
            self._trello_open_btn.pack(side="right", padx=(0, 2))
            # Read-only buffer (selectable + copyable, just not editable),
            # hide Save bar (saving doesn't apply to live feed).
            try:
                self._textarea.config(state="disabled")
            except tk.TclError:
                pass
            try:
                self._save_bar.pack_forget()
            except tk.TclError:
                pass
        else:
            if self._client:
                self._trello_status_lbl.config(
                    text="Not linked to Trello", fg=TEXT_GRAY)
                self._trello_pin_btn.pack(side="right", padx=(0, 6))
            else:
                self._trello_status_lbl.config(text="")
            # Editable buffer, show Save bar.
            try:
                self._textarea.config(state="normal")
            except tk.TclError:
                pass
            try:
                self._save_bar.pack(
                    side="bottom", fill="x", padx=10, pady=(4, 10))
            except tk.TclError:
                pass

    def _open_compose_dialog(self):
        """Modal dialog for composing a Trello comment. Stays out of the
        editor pane so the live feed has the full vertical real estate
        until the user actually wants to write something. Posts on
        Ctrl+Enter or via the Post button.

        Comment lands on the *active tab's* card so a multi-board user
        can post to either source by switching tabs first."""
        target_card_id = (self._trello_active_card_id
                          or self._trello_card_id)
        if not target_card_id:
            show_toast(self, "Pin to a Trello card first", kind="error")
            return
        dlg = tk.Toplevel(self)
        dlg.title(f"Comment on Trello — {self._client or ''}".rstrip(' —'))
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        if os.path.isfile(_ICON):
            try:
                dlg.iconbitmap(_ICON)
            except Exception:
                pass

        hdr = tk.Frame(dlg, bg=SUCCESS_BG, padx=14, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Add comment to {self._client or ''}",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=SUCCESS_BG, fg=SUCCESS_FG).pack(anchor="w")
        # Surface which card the post will land on — important when 2+
        # boards are linked and the user is mid-tab-switch.
        target_card = self._trello_card_cache.get(target_card_id, {})
        target_board = self._board_name_for(target_card.get("idBoard"))
        target_lane = trello_client.get_lane_name(
            target_card.get("idBoard"), target_card.get("idList"))
        target_bits = [b for b in (target_board, target_lane) if b]
        target_label = "  ·  ".join(target_bits) or "linked card"
        tk.Label(hdr, text=f"Posting to: {target_label}",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=SUCCESS_BG, fg=SUCCESS_FG).pack(anchor="w", pady=(2, 0))
        tk.Label(hdr,
                 text="Posts to Trello as the user whose token is "
                      "configured. Ctrl+Enter posts.",
                 font=("Segoe UI Variable", 8), bg=SUCCESS_BG, fg=TEXT_GRAY,
                 wraplength=440, justify="left").pack(anchor="w")

        body = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)
        compose = tk.Text(body, height=8, wrap="word",
                          font=("Segoe UI Variable", 10), relief="solid", bd=1,
                          bg=WHITE, fg=TEXT_DARK,
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=GREEN, padx=8, pady=6)
        compose.pack(fill="both", expand=True)
        compose.focus_set()

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        bot.pack(fill="x")

        # Single-element box so the post handler closure can flip state.
        # plain bool var would also work; box matches the rest of this file.
        posting = [False]

        def _do_post(_e=None):
            if posting[0]:
                return "break"
            text = compose.get("1.0", "end-1c").strip()
            if not text:
                show_toast(dlg, "Type something first", kind="info")
                return "break"
            posting[0] = True
            post_btn.config(state="disabled", text="Posting…")
            dlg.update_idletasks()
            try:
                result = trello_client.post_comment(target_card_id, text)
            except Exception as ex:
                show_toast(dlg, f"Trello post failed: {ex}", kind="error")
                post_btn.config(state="normal", text="Post comment")
                posting[0] = False
                return "break"
            if not result:
                show_toast(dlg, "Trello post returned no result",
                           kind="error")
                post_btn.config(state="normal", text="Post comment")
                posting[0] = False
                return "break"
            dlg.destroy()
            self._refresh_from_trello()
            show_toast(self, "Comment posted to Trello", kind="info")
            return "break"

        secondary_button(bot, "Cancel", padx=14, pady=4,
                          command=dlg.destroy
                          ).pack(side="right", padx=(8, 0))
        post_btn = done_button(
            bot, "Post comment", padx=18, pady=4,
            command=_do_post)
        post_btn.pack(side="right")
        tk.Label(bot, text="Ctrl+Enter to post",
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY
                 ).pack(side="right", padx=(0, 12))

        compose.bind("<Control-Return>", _do_post)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

        # Center on parent
        dlg.update_idletasks()
        try:
            px, py = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self.winfo_width(), self.winfo_height()
            w = max(dlg.winfo_reqwidth(), 480)
            h = max(dlg.winfo_reqheight(), 320)
            dlg.geometry(f"{w}x{h}+{px + (pw-w)//2}+{py + (ph-h)//3}")
        except Exception:
            pass

    def _pin_to_trello(self):
        """Open the shared pin picker for the current client. The dialog
        handles search + manual paste + persistence; we just re-load the
        client on save so the live feed picks up the new pin set."""
        if not self._client:
            return
        from job_widgets import open_trello_pin_dialog
        open_trello_pin_dialog(
            self, self._client,
            on_pinned=lambda _ids: self._load_client(
                self._year, self._client))

    def _open_aliases_dialog(self):
        """Open the shared search-aliases editor for the current client.
        Aliases feed every name-based lookup (SP folder scan, audit
        folder match, Trello card fuzzy match) so registering them once
        per client makes every tool find the job."""
        if not self._client:
            return
        from job_widgets import open_search_aliases_dialog
        open_search_aliases_dialog(self, self._client)

    # _show_card_picker was inlined into job_widgets.open_trello_pin_dialog;
    # JobNotesApp now calls that shared dialog from _pin_to_trello above.

    def _refresh_from_trello(self):
        """Manual ↻ — re-fetch every linked card and re-render. Cheap
        when nothing changed, always re-renders on click since the user
        explicitly asked. Active tab is preserved when the card is still
        present after refresh."""
        if not self._trello_card_ids:
            return
        text, ok = self._fetch_trello_text(self._trello_card_ids)
        if not ok:
            return
        self._loading = True
        try:
            self._textarea.config(state="normal")
            self._textarea.delete("1.0", "end")
            self._textarea.insert("1.0", text)
            self._textarea.edit_modified(False)
            self._textarea.config(state="disabled")
        finally:
            self._loading = False
        self._dirty = False
        self._ed_meta.config(
            text=f"refreshed {datetime.now().strftime('%b %d, %Y %I:%M %p')}")
        self._apply_message_tags()
        self._apply_info_tags()
        self._apply_md_styles()
        self._rebuild_trello_tabs()
        self._do_refresh_views()

    def _open_trello_card(self):
        """↗ — open the active tab's card in the user's browser. Falls
        back to a fuzzy lookup when no pin exists (shouldn't happen —
        toolbar only shows the button when linked — but defensive)."""
        target = self._trello_active_card_id or self._trello_card_id
        if target:
            url = f"https://trello.com/c/{target}"
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
        else:
            trello_client.open_card_for_client(self._client)

    # ── Trello live-poll loop ───────────────────────────────────────────
    # 30s tick that re-fetches the pinned card and re-renders only when
    # dateLastActivity moves. Stops itself when the panel is hidden /
    # destroyed / the user switches to an unpinned client. Cheap when
    # nothing changed (one HTTP HEAD-equivalent + cheap dict diff).
    _TRELLO_POLL_MS = 30_000

    def _start_trello_poll(self):
        """Schedule the next poll, cancelling any prior one. Idempotent —
        called from _load_client (when entering linked mode) and from the
        tick itself."""
        self._cancel_trello_poll()
        if not self._trello_card_ids:
            return
        self._trello_poll_after_id = self.after(
            self._TRELLO_POLL_MS, self._tick_trello_poll)

    def _cancel_trello_poll(self):
        if self._trello_poll_after_id is not None:
            try:
                self.after_cancel(self._trello_poll_after_id)
            except tk.TclError:
                pass
            self._trello_poll_after_id = None

    def _tick_trello_poll(self):
        """One poll iteration. Bails out fast if the panel is hidden or
        the user has navigated away from the linked client. Otherwise
        HEAD-fetches every linked card's dateLastActivity and re-renders
        ONLY when at least one card has moved — quiet polling on idle
        cards, no surprise refresh while the composer dialog is open."""
        self._trello_poll_after_id = None
        if not self._trello_card_ids:
            return
        try:
            mapped = bool(self.winfo_ismapped())
        except tk.TclError:
            mapped = False
        if not mapped:
            # Don't poll while hidden; on_show will resume.
            return
        # Light HEAD-style fetch per card: only need dateLastActivity
        # to decide whether to refresh. Cheap (no checklists/actions
        # payload). One round-trip per pinned card every 30s is fine —
        # most clients have 1 card; rare 2-3 card pins still total
        # sub-second per poll on a normal connection.
        any_changed = False
        for cid in self._trello_card_ids:
            try:
                head = trello_client._call(
                    f"/cards/{cid}",
                    params={"fields": "dateLastActivity,closed"})
            except Exception:
                continue
            if not head:
                continue
            new_activity = head.get("dateLastActivity")
            prev = self._trello_last_activity.get(cid)
            if new_activity and new_activity != prev:
                any_changed = True
        if any_changed:
            self._refresh_from_trello()
        self._start_trello_poll()

    def on_show(self):
        # ToolPanel hook — kicks the poll back on when the user navigates
        # back to this panel. _load_client also schedules on initial load,
        # so this is mainly for show-after-hide.
        if self._trello_card_ids:
            self._start_trello_poll()

    def on_hide(self):
        # Hidden panels shouldn't poll — wastes API quota and risks racing
        # with composer state when user comes back.
        self._cancel_trello_poll()

    def destroy(self):
        self._cancel_trello_poll()
        try:
            super().destroy()
        except Exception:
            pass

    def _save_current(self):
        if not self._client:
            return
        text = self._textarea.get("1.0", "end-1c")
        try:
            p = save_note(self._year, self._client, text)
        except OSError as ex:
            notify_error(self, "Save", str(ex), fatal=True)
            return
        self._dirty = False
        self._dirty_lbl.configure(text="")
        mtime = datetime.fromtimestamp(os.path.getmtime(p))
        self._ed_meta.config(text=f"saved {mtime.strftime('%b %d, %Y %I:%M %p')}")
        show_toast(self, "Saved", kind="success", duration=1600)
        self._refresh_saved_list()

    def _open_in_notepad(self):
        if not self._client:
            return
        p = _notes_path(self._year, self._client)
        if os.path.isfile(p):
            try:
                os.startfile(p)
            except OSError:
                pass

    # ── Timeline + expected files (pre-built, then toggled) ─────────────────
    def _build_timeline_widgets(self):
        """One row per stage built once. _render_timeline only configs them."""
        self._tl_rows = {}      # {label: (row, mark_lbl, text_lbl)}
        for label, _, _ in STAGES:
            row = tk.Frame(self._timeline_inner, bg=WHITE)
            mark = tk.Label(row, text="○", font=("Segoe UI Variable", 12, "bold"),
                            bg=WHITE, fg=TEXT_MUTED, width=2)
            mark.pack(side="left")
            txt = tk.Label(row, text=label, font=("Segoe UI Variable", 9),
                           bg=WHITE, fg=TEXT_MUTED, anchor="w")
            txt.pack(side="left", fill="x", expand=True)
            self._tl_rows[label] = (row, mark, txt)

        self._tl_empty = tk.Label(self._timeline_inner,
                                   text="No activities detected yet.",
                                   font=("Segoe UI Variable", 9, "italic"),
                                   bg=WHITE, fg=TEXT_GRAY)
        self._tl_divider = tk.Frame(self._timeline_inner, bg=BORDER, height=1)
        self._tl_latest = tk.Label(self._timeline_inner, text="",
                                    font=("Segoe UI Variable", 9, "bold"),
                                    bg=WHITE, fg=GREEN_DARK,
                                    wraplength=240, justify="left")

    def _build_expected_widgets(self):
        """One row per known expected-file built once.

        Each row holds a status mark (✓ green when present in the audit
        folder, ✗ red when missing, • neutral grey before audit data is
        available) plus the file label."""
        self._ef_rows = {}      # {filename: (row, mark_lbl, txt_lbl)}
        seen = set()
        for _, _, files in STAGES:
            for f in files:
                if f in seen:
                    continue
                seen.add(f)
                row = tk.Frame(self._expected_inner, bg=WHITE)
                mark = tk.Label(row, text="•", font=("Segoe UI Variable", 12, "bold"),
                                bg=WHITE, fg=GREEN_DARK, width=2)
                mark.pack(side="left")
                txt = tk.Label(row, text=f, font=("Segoe UI Variable", 9),
                               bg=WHITE, fg=TEXT_DARK,
                               anchor="w", wraplength=220, justify="left")
                txt.pack(side="left", fill="x", expand=True)
                self._ef_rows[f] = (row, mark, txt)
        self._ef_empty = tk.Label(self._expected_inner,
                                   text="(no required files yet)",
                                   font=("Segoe UI Variable", 9, "italic"),
                                   bg=WHITE, fg=TEXT_GRAY)

    def _render_timeline(self, stages):
        if not stages:
            for row, _, _ in self._tl_rows.values():
                row.pack_forget()
            self._tl_divider.pack_forget()
            self._tl_latest.pack_forget()
            self._tl_empty.pack(anchor="w")
            return
        self._tl_empty.pack_forget()
        seen_set = set(stages)
        # Re-pack in canonical STAGES order so rows always sit in stage order
        for label, _, _ in STAGES:
            row, mark, txt = self._tl_rows[label]
            seen = label in seen_set
            mark.config(text="✓" if seen else "○",
                        fg=GREEN_DARK if seen else "#CCCCCC")
            txt.config(font=("Segoe UI Variable", 9, "bold" if seen else "normal"),
                       fg=TEXT_DARK if seen else "#999999")
            row.pack_forget()
            row.pack(fill="x", pady=2)
        self._tl_divider.pack_forget()
        self._tl_divider.pack(fill="x", pady=(8, 6))
        self._tl_latest.config(text=f"Latest stage: {stages[-1]}")
        self._tl_latest.pack_forget()
        self._tl_latest.pack(anchor="w")

    def _render_expected(self, files):
        if not files:
            for entry in self._ef_rows.values():
                entry[0].pack_forget()
            self._ef_empty.pack(anchor="w")
            return
        self._ef_empty.pack_forget()
        # Hide all, then re-pack only the ones for current stages in order
        for entry in self._ef_rows.values():
            entry[0].pack_forget()
        missing = self._audit_missing  # None = no audit data yet
        for f in files:
            entry = self._ef_rows.get(f)
            if entry is None:
                continue
            row, mark, txt = entry
            if missing is None:
                mark.config(text="•", fg=TEXT_MUTED)
                txt.config(fg=TEXT_DARK)
            elif f in missing:
                mark.config(text="✗", fg=FLAG_RED)
                txt.config(fg=FLAG_RED)
            else:
                mark.config(text="✓", fg=GREEN_DARK)
                txt.config(fg=TEXT_DARK)
            row.pack(fill="x", pady=2)

    def _refresh_audit_status(self):
        """Run the live audit for the loaded client and stash the missing
        set so _render_expected can mark each row ✓/✗.

        Best-effort: if the audit base isn't reachable or the client folder
        can't be located, leave self._audit_missing as None so the panel
        falls back to the neutral • marks instead of surfacing an error
        (Job Notes shouldn't nag the user when the X: drive is offline)."""
        self._audit_missing = None
        if not self._client or not self._year:
            return
        # _year is a folder name like "2026 EMS Files" — pull the int year
        m = re.search(r"(20\d{2})", str(self._year))
        if not m:
            return
        year_int = int(m.group(1))
        try:
            results, err = audit_logic.audit_jobs(
                [self._client], AUDIT_BASE, year=year_int,
                folder_path_lookup=persistence.get_folder_path)
        except Exception:
            return
        if err or not results:
            return
        r = results[0]
        if not r.get("found"):
            return
        # check_photos called by audit_jobs only checks "Initial pics" without
        # log_rows. Re-run it here with stages derived from the current note
        # text so Demo / Mold Prep / Post / Reinspection rows resolve too.
        text = self._textarea.get("1.0", "end-1c")
        stages = parse_stages(text)
        # log_rows shape used by check_photos: (_, _, activity, _)
        log_rows = [(None, None, s, None) for s in stages]
        base = r["path"]
        ems = os.path.join(base, "EMS")
        contents = os.path.join(base, "CONTENTS")
        if os.path.isdir(ems):
            scan_base = ems
        elif os.path.isdir(contents):
            scan_base = contents
        else:
            scan_base = base
        try:
            photo_missing = audit_logic.check_photos(
                audit_logic.resolve_pics_dir(scan_base), log_rows=log_rows)
        except Exception:
            photo_missing = list(r.get("photo_issues", []))
        # Add the "Initial photo report" — that lives in EMS/DOCS, not PICS.
        try:
            report_missing = audit_logic.check_initial_photo_report(scan_base)
        except Exception:
            report_missing = []
        self._audit_missing = set(photo_missing) | set(report_missing)

    # ── Export ──────────────────────────────────────────────────────────────
    def _export_menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Export current client (Save As…)",
                      command=self._export_current)
        m.add_command(label="Export ALL notes to a folder…",
                      command=self._export_all)
        m.add_separator()
        m.add_command(label="Open notes folder in Explorer",
                      command=self._open_notes_folder)
        m.add_separator()
        m.add_command(label="Re-clean all saved notes…",
                      command=self._re_clean_all_notes)
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _re_clean_all_notes(self):
        """Sweep every saved .md note through the latest Trello cleanup
        logic. Useful after extending the parser (e.g. when (edited) was
        added) so old notes that never cleaned the first time pick up
        the fix retroactively. Each modified file is backed up first so
        the user can revert if the new cleaner does something wrong on
        a particular note."""
        if self._dirty and not messagebox.askyesno(
                "Unsaved changes",
                f"{self._client} has unsaved edits — those won't be touched, "
                "but the saved file on disk WILL be re-cleaned.\n\nProceed?",
                parent=self):
            return
        if not messagebox.askyesno(
                "Re-clean all saved notes?",
                "This sweeps every saved note through the current Trello "
                "cleanup pipeline so older notes pick up newer fixes (like "
                "(edited)-suffix recognition).\n\n"
                "Each modified file is backed up to "
                "<name>.md.<timestamp>.bak before being overwritten — you "
                "can revert any individual file from its backup if needed."
                "\n\nProceed?",
                parent=self):
            return
        try:
            changed, total = re_clean_all_notes()
        except Exception as ex:
            notify_error(self, "Re-clean", str(ex), fatal=True)
            return
        # If the loaded client's file got rewritten, refresh the editor
        # so the user sees the new content (without losing unsaved edits
        # — we only refresh the buffer when not dirty).
        if self._client and not self._dirty:
            try:
                fresh = load_note(self._year, self._client)
                cur = self._textarea.get("1.0", "end-1c")
                if fresh and fresh != cur:
                    self._loading = True
                    try:
                        self._textarea.config(state="normal")
                        self._textarea.delete("1.0", "end")
                        self._textarea.insert("1.0", fresh)
                        self._textarea.edit_modified(False)
                    finally:
                        self._loading = False
                    self._apply_message_tags()
                    self._apply_info_tags()
                    self._apply_md_styles()
                    self._do_refresh_views()
            except Exception:
                pass
        if total == 0:
            messagebox.showinfo("No notes found",
                "No saved notes to re-clean.", parent=self)
        else:
            messagebox.showinfo(
                "Re-clean complete",
                f"Updated {changed} of {total} note(s).\n\n"
                "Backups (.bak files) are alongside each modified note.",
                parent=self)

    def _export_current(self):
        if not self._client:
            messagebox.showinfo("Nothing loaded",
                                "Load a client first to export their note.",
                                parent=self)
            return
        if self._dirty:
            if messagebox.askyesno("Save first?",
                                   "You have unsaved changes — save before exporting?",
                                   parent=self):
                self._save_current()
        src = _notes_path(self._year, self._client)
        if not os.path.isfile(src):
            messagebox.showinfo("Nothing to export",
                                "This client has no saved note yet.",
                                parent=self)
            return
        dst = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".md",
            initialfile=f"{self._client} ({self._year}).md",
            filetypes=[("Markdown", "*.md"),
                       ("Text", "*.txt"),
                       ("All files", "*.*")])
        if not dst:
            return
        try:
            shutil.copy2(src, dst)
            show_toast(self, "Exported", kind="success", duration=2000)
        except OSError as ex:
            notify_error(self, "Export", str(ex), fatal=True)

    def _export_all(self):
        if not os.path.isdir(_NOTES_ROOT) or not list_saved_notes():
            messagebox.showinfo("Nothing to export",
                                "No notes saved yet.",
                                parent=self)
            return
        dst = filedialog.askdirectory(parent=self,
                                      title="Pick a folder to export notes into")
        if not dst:
            return
        target = os.path.join(dst, "EMS Job Notes")
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(_NOTES_ROOT, target)
            show_toast(self, "Exported all notes",
                       kind="success", duration=2400)
            try:
                os.startfile(target)
            except OSError:
                pass
        except OSError as ex:
            notify_error(self, "Export", str(ex), fatal=True)

    def _open_notes_folder(self):
        os.makedirs(_NOTES_ROOT, exist_ok=True)
        try:
            os.startfile(_NOTES_ROOT)
        except OSError:
            pass

    # ── Cross-tool entry point ──────────────────────────────────────────────
    def consume_cli_args(self, cli_args):
        """Called by the launcher when another panel navigates here.

        Accepts `--year=2026` and `--client=Smith John` to pre-load a note.
        Both are required to actually open a client.
        """
        year = None
        client = None
        for arg in cli_args or ():
            if arg.startswith("--year="):
                year = arg[len("--year="):]
            elif arg.startswith("--client="):
                client = arg[len("--client="):]
        if not (year and client):
            return
        # Map raw year ("2026") to the actual folder name shown in the dropdown
        # (e.g. "2026 EMS Files"). If no match, leave the dropdown alone.
        actual_year = None
        for y in self._year_dd["values"]:
            if year in y:
                actual_year = y
                break
        if actual_year:
            self._year_var.set(actual_year)
            self._refresh_clients()
            self._client_var.set(client)
            self._load_client(actual_year, client)

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def on_hide(self):
        if self._dirty:
            ans = messagebox.askyesnocancel(
                "Unsaved changes",
                f"Save changes to {self._client} before leaving?",
                parent=self)
            if ans is None:
                return False
            if ans:
                self._save_current()
        return True


def main(argv=None):
    run_standalone(JobNotesApp, geometry="1180x740", minsize=(900, 540))


if __name__ == "__main__":
    main()
