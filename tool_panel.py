"""
Embeddable-tool base class.

Each EMS tool used to be a `tk.Tk` subclass running in its own process. To get
a single-window experience the launcher hosts every tool as a sibling Frame
inside one Tk root. Tools that were originally Tk subclasses inherit from
ToolPanel here instead — it's a tk.Frame that absorbs the Tk-only methods
(title, geometry, iconbitmap, protocol, …) so existing tool code keeps
working unchanged.

Each tool's `def main()` calls `run_standalone(PanelClass, ...)` so direct
invocation (e.g. `python apa_monitor_gui.py`) still works for dev / debugging.

In standalone mode the Tk-only methods delegate to the toplevel root, so the
existing `self.title("…")` / `self.geometry("…")` calls behave exactly as
before. In embedded mode they're no-ops; the host owns title/geometry/icon.
"""
import os
import ctypes
import time
import tkinter as tk

import paths


# ── Dialog auto-fit + auto-center ──────────────────────────────────────────
# Applied class-wide via a bind_class("Toplevel", "<Map>", …) handler so
# every tk.Toplevel popup in every tool gets the same treatment without
# touching the ~67 call sites.
#
# Problem this fixes:
#   • Dialogs that set `top.geometry("WxH")` before packing children can
#     end up smaller than the actual requested content size, clipping the
#     bottom row of buttons. Tk *would* expand to fit if no geometry was
#     pinned, but an explicit geometry overrides it.
#   • Toplevels also default-position near the screen's top-left (or
#     wherever the WM decides) instead of centered on the parent
#     window — the user's focus has to jump across the monitor.
#
# Behavior:
#   • On the first <Map> event for any Toplevel, measure its packed
#     children's requested size. If the current geometry is smaller in
#     either axis, grow to fit (capped at 92% of screen so the OS
#     taskbar / titlebar stay visible). Otherwise leave the size alone.
#   • Re-center the window on its parent (or screen if parent is the
#     hidden root). Always — even for windows we didn't resize.
#   • Idempotent: a flag attribute on the Toplevel prevents re-firing
#     on subsequent <Map> events (minimize / restore).
#   • Opt-out: set `top._no_auto_resize = True` to skip the size step
#     while still getting recentered.
#   • Opt-out fully: set `top._no_auto_center = True` to skip both.

_AUTO_FIT_FLAG       = "_emsf_fit_done"
_AUTO_FIT_INSTALLED  = False
_TOPLEVEL_PATCHED    = False


def _patch_toplevel_init_for_fade():
    """Wrap `tk.Toplevel.__init__` so every new dialog starts at
    alpha=0 (fully transparent). The class-bound `<Map>` handler then
    fades it in to alpha=1 after auto-fit + center settle.

    Idempotent — guarded by a class attribute so repeated installs
    from every panel are safe. Native messagebox / Tk file dialogs
    don't go through `tk.Toplevel` (they call into the platform's
    `tk_messageBox` / `tk_getOpenFile`), so they're unaffected.

    Opt-out per dialog via `top._no_auto_fade = True` — set it before
    the first <Map>. Honors the existing `_no_auto_center` /
    `_no_auto_resize` flags too: a dialog that opts out of all auto
    behaviors stays fully visible from creation.
    """
    global _TOPLEVEL_PATCHED
    if _TOPLEVEL_PATCHED:
        return
    if getattr(tk.Toplevel, "_emsf_init_patched", False):
        _TOPLEVEL_PATCHED = True
        return
    orig_init = tk.Toplevel.__init__

    def _patched_init(self, *args, **kw):
        orig_init(self, *args, **kw)
        # Skip the fade when the caller opts out explicitly. We can't
        # know about per-instance flags here because __init__ is the
        # earliest hook, but a class can set a class-level flag.
        if getattr(self, "_no_auto_fade", False):
            return
        if getattr(type(self), "_no_auto_fade", False):
            return
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

    _patched_init._emsf_init_patched = True
    tk.Toplevel.__init__ = _patched_init
    tk.Toplevel._emsf_init_patched = True
    _TOPLEVEL_PATCHED = True


def _fade_in_after_fit(top, ms: int | None = None):
    """Tween a Toplevel from alpha=0 to alpha=1. Internal — `<Map>`
    handler calls this after auto-fit + center settle so the user
    sees a smooth materialize rather than a snap-into-existence flash."""
    if getattr(top, "_no_auto_fade", False):
        try:
            top.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        return
    try:
        from theme import tween_alpha, MOTION_SLOW
    except Exception:
        try:
            top.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        return
    duration = ms if ms is not None else MOTION_SLOW
    try:
        tween_alpha(top, 0.0, 1.0, ms=duration, steps=10)
    except Exception:
        try:
            top.attributes("-alpha", 1.0)
        except tk.TclError:
            pass


def center_dialog(top, parent=None):
    """Center `top` on `parent`. Falls back to centering on the screen
    when parent is None / not viewable. Only positions — does not
    resize. Safe to call any time after the window has been mapped."""
    try:
        top.update_idletasks()
    except tk.TclError:
        return
    if parent is None:
        try:
            m = top.master
            if isinstance(m, (tk.Tk, tk.Toplevel)):
                parent = m
            else:
                tl = top.nametowidget(top.winfo_parent()) if top.winfo_parent() else None
                parent = tl if isinstance(tl, (tk.Tk, tk.Toplevel)) else None
        except Exception:
            parent = None
    try:
        w = top.winfo_width()
        h = top.winfo_height()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        if parent is not None:
            try:
                viewable = bool(parent.winfo_viewable())
            except tk.TclError:
                viewable = False
        else:
            viewable = False
        if viewable:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
        else:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
        # Clamp inside the visible screen so a dialog can't land
        # off-screen on a multi-monitor / DPI-scaled setup.
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        top.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


def auto_fit_dialog(top, parent=None, *, max_frac=0.92):
    """If `top` is smaller than the size its packed children need, grow
    it to fit (capped at max_frac × screen). Then re-center on parent.
    Caller-facing wrapper around the class binding for the rare case
    when explicit control is needed (e.g. after the dialog dynamically
    adds rows post-creation)."""
    try:
        top.update_idletasks()
    except tk.TclError:
        return
    try:
        cur_w = top.winfo_width()
        cur_h = top.winfo_height()
        req_w = top.winfo_reqwidth()
        req_h = top.winfo_reqheight()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        max_w = int(sw * max_frac)
        max_h = int(sh * max_frac)
        # 4px of slack so border / theme padding doesn't snap a
        # single-pixel overflow into a scroll-needed state.
        new_w = min(max(cur_w, req_w + 4), max_w) if req_w > cur_w else cur_w
        new_h = min(max(cur_h, req_h + 4), max_h) if req_h > cur_h else cur_h
        if new_w != cur_w or new_h != cur_h:
            top.geometry(f"{new_w}x{new_h}")
            top.update_idletasks()
    except tk.TclError:
        return
    center_dialog(top, parent=parent)


def _on_toplevel_mapped(event):
    """Class-bound <Map> handler — auto-fit + center every Toplevel
    once, then fade it in from alpha=0 to 1. The first <Map> is when
    the WM actually shows the window, so children have already been
    laid out and reqsize is meaningful. Subsequent maps (un-minimize)
    are skipped via the flag."""
    w = event.widget
    if not isinstance(w, tk.Toplevel):
        return
    if getattr(w, _AUTO_FIT_FLAG, False):
        return
    setattr(w, _AUTO_FIT_FLAG, True)
    if getattr(w, "_no_auto_center", False):
        # Even when the caller pinned size+position explicitly we
        # still respect the fade-in unless they fully opted out.
        _fade_in_after_fit(w)
        return
    skip_size = bool(getattr(w, "_no_auto_resize", False))
    # Defer one idle tick so any packed children that registered just
    # before mapping have had a chance to register their reqsize.
    def _apply(ww=w, skip=skip_size):
        try:
            if not ww.winfo_exists():
                return
        except tk.TclError:
            return
        if skip:
            center_dialog(ww)
        else:
            auto_fit_dialog(ww)
        _fade_in_after_fit(ww)
    try:
        w.after_idle(_apply)
    except tk.TclError:
        pass


def install_auto_fit_handler(any_widget):
    """Register the class-wide <Map> handler + monkey-patch
    `tk.Toplevel.__init__` so every dialog starts at alpha=0 (the
    fade-in then runs from <Map>). Idempotent — the interpreter-
    scoped flag means repeated calls from every panel / every
    run_standalone are safe.
    """
    global _AUTO_FIT_INSTALLED
    if _AUTO_FIT_INSTALLED:
        return
    try:
        any_widget.bind_class("Toplevel", "<Map>",
                               _on_toplevel_mapped, add="+")
        _patch_toplevel_init_for_fade()
        _AUTO_FIT_INSTALLED = True
    except tk.TclError:
        pass


class ToolPanel(tk.Frame):
    """tk.Frame with Tk-root API stand-ins.

    Set `panel._embedded = True` before the panel does any UI work to make
    title/geometry/icon calls inert; otherwise they pass through to the
    toplevel Tk root (standalone mode).
    """

    TOOL_TITLE = "Tool"
    TOOL_AUMID = None  # optional Windows AppUserModelID for standalone mode

    # Window geometry persistence — set TOOL_GEOMETRY_KEY in a subclass to
    # remember the standalone window's size/position across sessions. Embedded
    # mode is a no-op (the launcher owns its own geometry); without a key
    # restore/save quietly do nothing.
    TOOL_GEOMETRY_KEY = None
    DEFAULT_GEOMETRY  = None

    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        # Auto-detect embedding: if parent is a tk.Tk we're standalone, otherwise embedded.
        # This must be set BEFORE subclass __init__ runs any self.title()/geometry() calls,
        # which happens automatically because tk.Frame.__init__ above completes first.
        self._embedded = not isinstance(parent, tk.Tk)
        self._panel_title = self.TOOL_TITLE
        self._on_close_cb = None
        self._title_var = None    # host can attach a tk.StringVar
        self.host = None          # host (LauncherApp) sets this when embedding
        # One-time install of the class-wide Toplevel auto-fit / center
        # handler. Idempotent — first panel built wins, the rest no-op.
        # Lives here (vs. only in run_standalone) so embedded launcher
        # tools that never go through run_standalone still get it.
        try:
            install_auto_fit_handler(self)
        except Exception:
            pass
        # Schedule one auto-tooltip sweep on idle so subclass _build_ui
        # has finished populating children by the time we walk the tree.
        # Idempotent — the per-widget marker prevents double-attaching
        # if a panel also schedules its own follow-up sweep after a
        # dynamic re-render.
        try:
            self.after_idle(self.sweep_tooltips)
        except Exception:
            pass

    def sweep_tooltips(self):
        """Public re-sweep — panels with dynamic content (audit cards,
        hygiene sections) call this after a major re-render so newly-
        spawned buttons get default tooltips. Safe to call repeatedly."""
        try:
            attach_default_tooltips(self)
        except Exception:
            pass

    # ── helpers ──────────────────────────────────────────────────────────────
    def _toplevel(self):
        try:
            return self.winfo_toplevel()
        except Exception:
            return None

    # ── Tk-root API stand-ins ────────────────────────────────────────────────
    def title(self, t=None):
        if t is None:
            return self._panel_title
        self._panel_title = t
        if self._title_var is not None:
            try:
                self._title_var.set(t)
            except Exception:
                pass
        if not self._embedded:
            tl = self._toplevel()
            if tl is not None:
                try:
                    tl.title(t)
                except Exception:
                    pass

    def geometry(self, geo=None):
        # Getter: return current toplevel geometry string (used by panels that
        # persist their last window size).
        if geo is None:
            tl = self._toplevel()
            if tl is not None:
                try:
                    return tl.geometry()
                except Exception:
                    pass
            return ""
        # Setter: only honored in standalone mode
        if not self._embedded:
            tl = self._toplevel()
            if tl is not None:
                try:
                    tl.geometry(geo)
                except Exception:
                    pass

    def _delegate_if_standalone(self, attr, *args, **kwargs):
        if self._embedded:
            return None
        tl = self._toplevel()
        if tl is None:
            return None
        fn = getattr(tl, attr, None)
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None

    def iconbitmap(self, *a, **kw):  return self._delegate_if_standalone("iconbitmap", *a, **kw)
    def iconphoto(self, *a, **kw):   return self._delegate_if_standalone("iconphoto", *a, **kw)
    def minsize(self, *a, **kw):     return self._delegate_if_standalone("minsize", *a, **kw)
    def maxsize(self, *a, **kw):     return self._delegate_if_standalone("maxsize", *a, **kw)
    def resizable(self, *a, **kw):   return self._delegate_if_standalone("resizable", *a, **kw)
    def attributes(self, *a, **kw):  return self._delegate_if_standalone("attributes", *a, **kw)
    def wm_attributes(self, *a, **kw): return self._delegate_if_standalone("wm_attributes", *a, **kw)
    def state(self, *a, **kw):
        if self._embedded:
            return "normal"
        return self._delegate_if_standalone("state", *a, **kw)

    def protocol(self, name, callback=None):
        if name == "WM_DELETE_WINDOW" and callback is not None:
            self._on_close_cb = callback
            # Also wire it on the toplevel in standalone mode so the X button works
            if not self._embedded:
                tl = self._toplevel()
                if tl is not None:
                    try:
                        def _wrap():
                            try:
                                callback()
                            finally:
                                # Default behaviour was self.destroy() inside
                                # callback; if it didn't destroy, we shouldn't.
                                pass
                        tl.protocol("WM_DELETE_WINDOW", _wrap)
                    except Exception:
                        pass

    # ── Geometry persistence (standalone only) ──────────────────────────────
    def restore_geometry(self):
        """Apply saved or default geometry to the toplevel. No-op when embedded.

        Reads from persistence under TOOL_GEOMETRY_KEY, falls back to
        DEFAULT_GEOMETRY. Either-or — if neither is set, nothing happens.
        """
        if self._embedded:
            return
        geo = None
        key = self.TOOL_GEOMETRY_KEY
        if key:
            try:
                import persistence
                geo = persistence.get_geometry(key)
            except Exception:
                geo = None
        target = geo or self.DEFAULT_GEOMETRY
        if target:
            self.geometry(target)

    def save_geometry(self):
        """Persist current toplevel geometry under TOOL_GEOMETRY_KEY.

        No-op when embedded — `self.geometry()` would return the launcher
        window's geometry, which would clobber the saved standalone size.
        """
        if self._embedded or not self.TOOL_GEOMETRY_KEY:
            return
        try:
            import persistence
            persistence.set_geometry(self.TOOL_GEOMETRY_KEY, self.geometry())
        except Exception:
            pass

    # ── Shared chrome helpers ───────────────────────────────────────────────
    def build_header(self, title, subtitle=None, pady=12):
        """Pack the standard green title bar at the top of this panel.

        Skipped automatically when embedded — the launcher's toolstrip
        already shows the section, so the band would be visual noise.
        Returns the header frame (or None when embedded) so callers can
        attach extras if needed.

        Uses CTk widgets when available for the modern look (rounded
        corners aren't visible on a flush band, but the antialiased
        font rendering and dark-mode awareness are). Falls back to
        plain tk so dev installs without ctk still work.
        """
        if self._embedded:
            return None
        # Lazy imports — keeps tool_panel.py free of theme/circular deps.
        from theme import GREEN, WHITE
        try:
            import customtkinter as ctk
            height = 72 if subtitle else 52
            hdr = ctk.CTkFrame(self, fg_color=GREEN, corner_radius=0,
                               height=height)
            hdr.pack(fill="x")
            hdr.pack_propagate(False)
            ctk.CTkLabel(hdr, text=title,
                         font=ctk.CTkFont("Segoe UI Variable", 16, "bold"),
                         text_color=WHITE
                         ).pack(pady=(12 if subtitle else 14, 0))
            if subtitle:
                ctk.CTkLabel(hdr, text=subtitle,
                             font=ctk.CTkFont("Segoe UI Variable", 10),
                             text_color="#C8E6D4").pack(pady=(2, 12))
            return hdr
        except ImportError:
            hdr = tk.Frame(self, bg=GREEN, pady=pady)
            hdr.pack(fill="x")
            tk.Label(hdr, text=title,
                     font=("Segoe UI Variable", 14, "bold"),
                     bg=GREEN, fg=WHITE).pack()
            if subtitle:
                tk.Label(hdr, text=subtitle,
                         font=("Segoe UI Variable", 9),
                         bg=GREEN, fg="#B2DFC4").pack(pady=(2, 0))
            return hdr

    def confirm_save_before(self, message, on_save, parent=None):
        """Standard 'unsaved changes' guard — yes saves, no discards, cancel
        vetoes. Returns True when navigation/close should proceed, False
        when the user cancelled.

        Call from on_hide() when leaving a tool with dirty state. `on_save`
        is the callable to run when the user picks Save (typically self._save).
        """
        from tkinter import messagebox
        ans = messagebox.askyesnocancel(
            "Unsaved changes", message,
            parent=parent if parent is not None else self)
        if ans is None:
            return False
        if ans:
            try:
                on_save()
            except Exception:
                pass
        return True

    # ── Cross-tool navigation ────────────────────────────────────────────────
    def navigate_to(self, tool_key, *cli_args):
        """Switch focus to another tool. In embedded mode swaps panels in
        the host launcher; in standalone mode falls back to subprocess spawn."""
        if self.host is not None:
            self.host.show_tool(tool_key, cli_args=cli_args)
        else:
            paths.spawn_tool(tool_key, *cli_args)

    # ── Lifecycle hooks the host calls ───────────────────────────────────────
    def on_show(self):
        """Called when the host brings this panel to the front."""
        pass

    def on_hide(self):
        """Called before the host swaps to a different panel.

        Return False to veto the navigation (e.g. an unsaved-changes prompt
        in APA Monitor that the user cancelled). Default = always allow.
        """
        return True

    def on_close(self):
        """Called when the whole app is closing — runs the WM_DELETE_WINDOW callback."""
        if self._on_close_cb:
            try:
                self._on_close_cb()
            except Exception:
                pass

    # ── Inline loading throbber ─────────────────────────────────────────────
    # Any panel can call self.show_loading("Loading…") before kicking off a
    # slow op (run-doc parse, network folder scan, audit run, etc.) and
    # self.hide_loading() when done. The overlay covers the panel via place()
    # so layout doesn't shift; safe to call repeatedly.
    def show_loading(self, message="Loading…"):
        self.hide_loading()
        ov = LoadingOverlay(self, message=message)
        ov.place(relx=0, rely=0, relwidth=1, relheight=1)
        ov.lift()
        ov.start()
        self._loading_overlay = ov
        # Force the overlay to paint before the caller blocks the UI thread
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def hide_loading(self):
        ov = getattr(self, "_loading_overlay", None)
        if ov is None:
            return
        try:
            ov.stop()
            ov.destroy()
        except tk.TclError:
            pass
        self._loading_overlay = None


# ── Responsive action bar ───────────────────────────────────────────────────
class ResponsiveActionBar(tk.Frame):
    """Bottom action bar that flows from one row to two when the window is
    too narrow to fit every button on a single line.

    Usage:
        bar = ResponsiveActionBar(parent, root_widget=self, bg=BG, padx=14, pady=10)
        bar.pack(fill="x")
        bar.add(save_btn,    group="primary",   side="right", padx=(0, 8))
        bar.add(reload_btn,  group="secondary", side="left",  padx=(0, 6))
        bar.add(export_btn,  group="secondary", side="left",  padx=(0, 6))

    Layout:
      • One-row mode (wide): every widget packed into a single row, with
        primary-group widgets right-aligned (Save flow) and secondary-
        group widgets left-aligned (utilities).
      • Two-row mode (narrow): secondary widgets get their own row above
        the primary row so nothing clips off-screen.

    The bar listens to the supplied `root_widget`'s `<Configure>` events
    (debounced 40ms) and switches modes automatically. Pass the panel
    itself or whichever ancestor controls the resize-driving width.
    """

    def __init__(self, parent, root_widget=None, bg=None, padx=14, pady=10,
                 **frame_kwargs):
        kwargs = {"padx": padx, "pady": pady}
        if bg is not None:
            kwargs["bg"] = bg
        kwargs.update(frame_kwargs)
        super().__init__(parent, **kwargs)
        self._bg_color = bg
        # Renamed from `_root` — that attribute name shadowed
        # tkinter.Misc._root (a method that returns the toplevel),
        # which caused `'tk.Widget' object is not callable` style
        # bugs whenever code invoked .place() / .pack() / .configure()
        # on instances of subclasses that happened to set self._root.
        # See dev_lint.py SHADOW-TK check.
        self._resize_root = root_widget or parent

        self._primary_row = tk.Frame(self, bg=bg)
        self._primary_row.pack(fill="x")
        self._secondary_row = tk.Frame(self, bg=bg)
        # secondary_row is packed dynamically by _apply_*_row().

        # Each entry: {"widget", "group", "side", "padx"}
        self._items = []
        self._mode = None      # "one" or "two"
        self._after_id = None

        # Default to one-row; first <Configure> snaps to two-row if needed.
        self._apply_one_row()
        self._mode = "one"
        self._resize_root.bind("<Configure>", self._on_root_configure, add="+")
        # Kick a relayout once the panel actually has its real geometry.
        self.after(50, self._relayout)

    def add(self, widget, group="secondary", side="left", padx=(0, 6)):
        """Register a widget with the bar. Group must be 'primary' (Save
        flow — always on the bottom row) or 'secondary' (utilities — moved
        to the top row when there's not enough horizontal space)."""
        if group not in ("primary", "secondary"):
            raise ValueError(f"group must be 'primary' or 'secondary', got {group!r}")
        self._items.append({
            "widget": widget, "group": group, "side": side, "padx": padx,
        })
        # Pack immediately into the current layout so the caller sees the
        # widget appear right away.
        target = (self._primary_row if self._mode != "two"
                  else (self._secondary_row if group == "secondary"
                        else self._primary_row))
        try:
            widget.pack(in_=target, side=side, padx=padx)
        except tk.TclError:
            pass

    def _apply_one_row(self):
        try: self._secondary_row.pack_forget()
        except Exception: pass
        for it in self._items:
            try: it["widget"].pack_forget()
            except Exception: pass
        for it in self._items:
            try:
                it["widget"].pack(in_=self._primary_row,
                                  side=it["side"], padx=it["padx"])
            except tk.TclError:
                pass

    def _apply_two_rows(self):
        for it in self._items:
            try: it["widget"].pack_forget()
            except Exception: pass
        try: self._secondary_row.pack_forget()
        except Exception: pass
        self._secondary_row.pack(fill="x", pady=(0, 6),
                                 before=self._primary_row)
        for it in self._items:
            target = (self._secondary_row if it["group"] == "secondary"
                      else self._primary_row)
            try:
                it["widget"].pack(in_=target, side=it["side"], padx=it["padx"])
            except tk.TclError:
                pass

    def _relayout(self, _e=None):
        try:
            w = self._resize_root.winfo_width()
        except tk.TclError:
            return
        if w <= 1 or not self._items:
            return
        # Estimate one-row width from each widget's natural reqwidth.
        try:
            need = sum(it["widget"].winfo_reqwidth() + 12
                       for it in self._items) + 32
        except tk.TclError:
            return
        want_two = w < need
        if want_two and self._mode != "two":
            self._apply_two_rows()
            self._mode = "two"
        elif (not want_two) and self._mode != "one":
            self._apply_one_row()
            self._mode = "one"

    def _on_root_configure(self, _e=None):
        # Debounce — Configure fires per-pixel during drag-resize.
        if self._after_id is not None:
            try: self.after_cancel(self._after_id)
            except Exception: pass
        self._after_id = self.after(40, self._relayout)


# ── Responsive snap ─────────────────────────────────────────────────────────
class ResponsiveSnap:
    """Reflow a small widget between two homes based on window width.

    The pattern: a primary row (file picker, top form) plus a secondary
    block (section checkboxes, action buttons). When the window is wide
    enough, the secondary block sits at the right edge of the primary
    row. When narrow, it falls back to its own row below.

    Usage:
        # primary row that holds the main content
        top_row = tk.Frame(self, ...)
        top_row.pack(fill="x")
        # ... primary widgets in top_row ...

        # secondary block — owns its narrow-mode home and the movable inner.
        # IMPORTANT: movable's parent must be `self`, NOT narrow_row. Tk
        # only allows pack(in_=X) when X is the slave's parent or a
        # descendant of it; if movable's parent is narrow_row, Tk refuses
        # to pack it into top_row (a sibling) and the widget vanishes.
        narrow_row = tk.Frame(self, ...)
        narrow_row.pack(fill="x")
        movable = tk.Frame(self, ...)                  # parent = self
        movable.pack(in_=narrow_row, side="left", anchor="w")
        # ... secondary widgets in movable ...

        ResponsiveSnap(self,
                       inline_parent=top_row,
                       narrow_parent=narrow_row,
                       movable=movable,
                       narrow_before=status_label)

    The helper observes `<Configure>` on the panel (debounced 40ms),
    measures both pieces' natural widths, and switches modes when needed.
    """

    def __init__(self, root, *,
                 inline_parent, narrow_parent, movable,
                 narrow_before=None, narrow_after=None,
                 inline_side="right", inline_anchor="e",
                 inline_padx=(20, 0),
                 narrow_side="left", narrow_anchor="w",
                 padding=60):
        self.root            = root
        self.inline_parent   = inline_parent
        self.narrow_parent   = narrow_parent
        self.movable         = movable
        self.narrow_before   = narrow_before
        self.narrow_after    = narrow_after
        self.inline_side     = inline_side
        self.inline_anchor   = inline_anchor
        self.inline_padx     = inline_padx
        self.narrow_side     = narrow_side
        self.narrow_anchor   = narrow_anchor
        self.padding         = padding
        self._inline         = False
        self._after_id       = None
        try:
            root.bind("<Configure>", self._on_resize, add="+")
            root.after(50, self.apply)
        except tk.TclError:
            pass

    def _on_resize(self, _e=None):
        if self._after_id is not None:
            try: self.root.after_cancel(self._after_id)
            except Exception: pass
        try:
            self._after_id = self.root.after(40, self.apply)
        except tk.TclError:
            self._after_id = None

    def apply(self):
        self._after_id = None
        try:
            w        = self.root.winfo_width()
            inline_w = self.inline_parent.winfo_reqwidth()
            mov_w    = self.movable.winfo_reqwidth()
        except tk.TclError:
            return
        if w <= 1:
            return
        want_inline = w >= inline_w + mov_w + self.padding
        if want_inline and not self._inline:
            try: self.movable.pack_forget()
            except Exception: pass
            try: self.narrow_parent.pack_forget()
            except Exception: pass
            try:
                self.movable.pack(in_=self.inline_parent,
                                   side=self.inline_side,
                                   anchor=self.inline_anchor,
                                   padx=self.inline_padx)
            except tk.TclError:
                return
            self._inline = True
        elif (not want_inline) and self._inline:
            try: self.movable.pack_forget()
            except Exception: pass
            kw = {"fill": "x"}
            if self.narrow_before is not None:
                kw["before"] = self.narrow_before
            elif self.narrow_after is not None:
                kw["after"]  = self.narrow_after
            try:
                self.narrow_parent.pack(**kw)
                self.movable.pack(in_=self.narrow_parent,
                                   side=self.narrow_side,
                                   anchor=self.narrow_anchor)
            except tk.TclError:
                return
            self._inline = False


# ── Loading overlay ─────────────────────────────────────────────────────────
class LoadingOverlay(tk.Frame):
    """A full-area spinner shown while a panel is loading.

    Two layouts:
        - simple: just spinner + message (default — what panel
          construction uses while their slow __init__ runs).
        - with_progress: adds a second label below the message line
          that callers can rewrite via `set_progress(text)`. Used by
          the launcher's startup splash to surface 'Preparing tools
          N/M…' so the user can see motion during the preload sweep.
    """

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, parent, message="Loading…",
                 bg=None, spinner_fg=None, text_fg=None,
                 with_progress=False, brand=""):
        # Defaults pulled from the live theme so the overlay flips
        # with light/dark mode.
        from theme import BG as _BG, GREEN as _GREEN, TEXT_GRAY as _TXG
        from theme import TEXT_DARK as _TXD
        if bg is None: bg = _BG
        if spinner_fg is None: spinner_fg = _GREEN
        if text_fg is None: text_fg = _TXG
        super().__init__(parent, bg=bg)
        self._frame_idx = 0
        self._running = False

        center = tk.Frame(self, bg=bg)
        center.place(relx=0.5, rely=0.5, anchor="center")
        if brand:
            tk.Label(center, text=brand,
                     font=("Fraunces", 20, "bold"),
                     bg=bg, fg=_TXD).pack(pady=(0, 14))
        self._spinner_lbl = tk.Label(center, text=self.FRAMES[0],
                                      font=("Segoe UI Variable", 32, "bold"),
                                      bg=bg, fg=spinner_fg)
        self._spinner_lbl.pack()
        self._message_lbl = tk.Label(
            center, text=message,
            font=("Segoe UI Variable", 10),
            bg=bg, fg=text_fg)
        self._message_lbl.pack(pady=(6, 0))
        self._progress_lbl = None
        if with_progress:
            self._progress_lbl = tk.Label(
                center, text="",
                font=("Segoe UI Variable", 9, "italic"),
                bg=bg, fg=text_fg)
            self._progress_lbl.pack(pady=(2, 0))

    def set_message(self, text):
        """Replace the main message line. Safe after destroy — silently
        no-ops if the widget is gone."""
        try:
            if self._message_lbl.winfo_exists():
                self._message_lbl.config(text=text)
        except tk.TclError:
            pass

    def set_progress(self, text):
        """Replace the optional sub-message line. No-op when the
        overlay was constructed without `with_progress=True` or when
        the widget has been destroyed."""
        lbl = self._progress_lbl
        if lbl is None:
            return
        try:
            if lbl.winfo_exists():
                lbl.config(text=text)
        except tk.TclError:
            pass

    def start(self):
        self._running = True
        self._tick()

    def stop(self):
        self._running = False

    def _tick(self):
        if not self._running:
            return
        self._frame_idx = (self._frame_idx + 1) % len(self.FRAMES)
        try:
            self._spinner_lbl.config(text=self.FRAMES[self._frame_idx])
        except tk.TclError:
            return  # widget destroyed
        self.after(80, self._tick)


# ── Scrollable frame ────────────────────────────────────────────────────────
class ScrollableFrame(tk.Frame):
    """Vertical scrolling container — canvas + scrollbar + inner frame, with
    a panel-scoped mousewheel binding (no bind_all leak) and a ready-made
    inner frame whose width tracks the canvas.

    Usage:
        wrap = ScrollableFrame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        # add content to wrap.inner
        tk.Label(wrap.inner, text="hi").pack(...)

    Why a panel-scoped bindtag instead of bind_all:
        bind_all on `<MouseWheel>` leaks across panels — when the launcher
        swaps tools, wheel events keep scrolling a hidden canvas of the
        previous panel. The bindtag approach scopes the wheel handler to
        this widget tree only, and is the same pattern the APA Monitor
        switched to after that bug surfaced.
    """

    _bindtag_counter = 0

    def __init__(self, parent, bg=None, canvas_bg=None,
                 padx=0, pady=0, **frame_kwargs):
        kwargs = {"padx": padx, "pady": pady}
        if bg is not None:
            kwargs["bg"] = bg
        kwargs.update(frame_kwargs)
        super().__init__(parent, **kwargs)

        cbg = canvas_bg if canvas_bg is not None else bg
        self.canvas = tk.Canvas(self, highlightthickness=0,
                                **({"bg": cbg} if cbg is not None else {}))
        self.scrollbar = tk.Scrollbar(self, orient="vertical",
                                       command=self.canvas.yview)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(self.scrollbar)
        except Exception:
            pass
        # yscrollincrement=1 → "units" in yview_scroll mean pixels.
        # Tk's default of 0 makes each unit ≈10% of the canvas height,
        # which lands the wheel mid-card and visually clips the row
        # the user is reading ("split frames"). Pixel-precise units
        # let us scroll a fixed, sub-card distance per wheel tick.
        self.canvas.configure(yscrollcommand=self.scrollbar.set,
                              yscrollincrement=1)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas,
                              **({"bg": bg} if bg is not None else {}))
        self._window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw")

        # Inner content height drives scrollregion; canvas width drives inner.
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Panel-scoped mousewheel — bindtag instead of bind_all so the
        # binding doesn't leak across launcher panel swaps.
        ScrollableFrame._bindtag_counter += 1
        self._scroll_tag = f"emsscroll_{ScrollableFrame._bindtag_counter}"
        # Bind the wheel handler against the unique tag and add the tag to
        # every descendant of the inner frame after each layout pass.
        self.bind_class(self._scroll_tag, "<MouseWheel>", self._on_wheel)
        self._attach_wheel(self.canvas)
        self._attach_wheel(self.inner)
        # Debounced re-walk of descendants so children added to .inner
        # after construction (which is the common case — tools render into
        # inner from a thread, after a doc parse, etc.) inherit the wheel
        # binding without callers needing to remember to call attach_wheel.
        self._wheel_after_id = None
        # Debounced scrollregion recompute. Streaming renders fire one
        # `<Configure>` per new card at 40 fps; each immediate
        # `bbox("all")` + `configure(scrollregion=...)` re-walks every
        # child and forces a canvas reflow. With many cards on screen
        # those reflows compete with the user's scroll repaints and
        # show up as tearing. Coalescing into a single deferred
        # update per layout-burst eliminates that.
        self._scrollregion_after_id = None

    def _on_inner_configure(self, _e=None):
        # Coalesce the scrollregion update — see __init__ comment.
        # 40 ms is below human perception for "scroll bar didn't update
        # exactly when card landed" but well above the 25 ms streaming
        # drain interval, so a burst of card additions resolves to one
        # bbox walk instead of N.
        try:
            if self._scrollregion_after_id is not None:
                self.canvas.after_cancel(self._scrollregion_after_id)
        except Exception:
            pass
        try:
            self._scrollregion_after_id = self.canvas.after(
                40, self._apply_scrollregion)
        except tk.TclError:
            self._scrollregion_after_id = None
        # Schedule a deferred walk to attach the wheel tag to any new
        # descendants. Debounced so a render pass that adds many widgets
        # only triggers ONE walk after the layout settles, not one per
        # child. _attach_wheel is idempotent so re-walking is cheap.
        try:
            if self._wheel_after_id is not None:
                self.canvas.after_cancel(self._wheel_after_id)
        except Exception:
            pass
        try:
            self._wheel_after_id = self.canvas.after(
                60, self._walk_attach_descendants)
        except tk.TclError:
            self._wheel_after_id = None

    def _apply_scrollregion(self):
        self._scrollregion_after_id = None
        try:
            new_bbox = self.canvas.bbox("all")
            old_region = self.canvas.cget("scrollregion") or ""
            self.canvas.configure(scrollregion=new_bbox)
        except tk.TclError:
            return
        # When the scrollregion grew significantly (streaming render
        # adding cards while the user was already scrolling), any
        # pending wheel delta from BEFORE the grow is stale — it was
        # computed against the old, smaller region and would now apply
        # against the larger one in surprising ways. Drop it so the
        # next genuine wheel event starts from a clean slate. Same
        # reasoning applies to a shrink (panel re-render with fewer
        # rows).
        if new_bbox and isinstance(new_bbox, tuple) and len(new_bbox) >= 4:
            try:
                old_parts = [int(float(p)) for p in (old_region or "0 0 0 0").split()]
                old_h = max(0, old_parts[3] - old_parts[1]) if len(old_parts) >= 4 else 0
            except (ValueError, IndexError):
                old_h = 0
            new_h = new_bbox[3] - new_bbox[1]
            if abs(new_h - old_h) > 100:
                self._pending_wheel_delta = 0
                flush_id = getattr(self, "_wheel_flush_id", None)
                if flush_id is not None:
                    try:
                        self.canvas.after_cancel(flush_id)
                    except Exception:
                        pass
                self._wheel_flush_id = None

    def _walk_attach_descendants(self):
        self._wheel_after_id = None
        try:
            self.attach_wheel(self.inner)
        except tk.TclError:
            pass

    def _on_canvas_configure(self, e):
        try:
            self.canvas.itemconfig(self._window, width=e.width)
        except tk.TclError:
            pass

    # Pixels to scroll per wheel notch. 50px ≈ 2-3 lines of text,
    # smaller than the previous 60 so each step is a comfortable
    # sub-card increment for Tk to paint inside one frame.
    _WHEEL_PX_PER_NOTCH = 50
    # Coalesce wheel events to ~30fps. 16ms (60fps) was too tight on
    # card-heavy panels — each card has dozens of native HWND
    # children (every tk.Frame/Label/Button is a Windows window),
    # and a single scroll triggers a SetWindowPos for every visible
    # child plus a canvas repaint. With ~600 HWNDs to move, Tk
    # often can't finish a frame inside 16ms and the user sees
    # partial paint = tearing. 33ms gives the OS a full frame of
    # breathing room to complete the repaint cleanly.
    _WHEEL_FRAME_MS = 33

    def _on_wheel(self, e):
        try:
            if not self.canvas.winfo_exists() or not self.canvas.winfo_ismapped():
                return
        except tk.TclError:
            return
        # Accumulate the wheel delta and schedule a single scroll-flush
        # for this frame. Subsequent wheel events within the frame just
        # add to the pending delta without re-scheduling.
        if not hasattr(self, "_pending_wheel_delta"):
            self._pending_wheel_delta = 0
            self._wheel_flush_id = None
        self._pending_wheel_delta += e.delta
        if self._wheel_flush_id is None:
            try:
                self._wheel_flush_id = self.canvas.after(
                    self._WHEEL_FRAME_MS, self._flush_wheel)
            except tk.TclError:
                self._wheel_flush_id = None
        return "break"

    def _flush_wheel(self):
        """Apply the accumulated wheel delta as a single yview_scroll.
        One scroll per frame keeps the canvas paints serialized so a
        rapid wheel-spin doesn't tear the visible region.

        Clamp the per-frame scroll distance: a fast wheel-spin can
        accumulate 5+ notches in 16 ms (= 300+ pixels), and a single
        300 px yview_scroll is too big for Tk to repaint atomically
        on a card-heavy page — the half-painted result reads as
        tearing. Capping per frame and re-queueing the leftover for
        the next frame turns one chunky jump into a paced animation
        that the OS can keep up with.

        Drain on boundary: if the canvas is clamped at top/bottom and
        the pending delta is pushing into the boundary, discard the
        leftover rather than re-queueing. Otherwise a wheel-spin past
        the bottom during page-load builds a stale pile of down-delta
        that swallows any subsequent up-wheel events for hundreds of
        ms — i.e., the "scroll broken until I use the sidebar" bug.
        """
        self._wheel_flush_id = None
        delta = getattr(self, "_pending_wheel_delta", 0)
        self._pending_wheel_delta = 0
        if not delta:
            return
        try:
            if not self.canvas.winfo_exists() or not self.canvas.winfo_ismapped():
                return
        except tk.TclError:
            return
        notches = delta / 120.0
        pixels = int(-notches * self._WHEEL_PX_PER_NOTCH)
        if not pixels:
            return
        # Boundary-clamp guard. If the canvas is already at the top
        # (fraction 0.0) and the user is asking for more up-scroll, OR
        # at the bottom (fraction 1.0) and asking for more down-scroll,
        # there's nothing to do — and re-queueing the leftover would
        # just trap stale delta that bites the next wheel event.
        try:
            first, last = self.canvas.yview()
        except (tk.TclError, ValueError):
            first, last = 0.0, 1.0
        if pixels > 0 and last >= 0.9999:
            # At/past bottom, user pushing down: discard.
            return
        if pixels < 0 and first <= 0.0001:
            # At/before top, user pushing up: discard.
            return
        # Cap per-frame scroll. ~120 px ≈ 4 lines of text per frame at
        # 60 fps = roughly screen-height-per-half-second, which is a
        # comfortable scroll rate. Anything bigger is what causes
        # paint to outrun the next vsync.
        max_per_frame = 120
        if abs(pixels) > max_per_frame:
            sign = 1 if pixels > 0 else -1
            applied = sign * max_per_frame
            leftover = pixels - applied
            # Re-queue leftover delta so the next frame consumes it.
            self._pending_wheel_delta += int(-leftover / self._WHEEL_PX_PER_NOTCH * 120)
            try:
                self._wheel_flush_id = self.canvas.after(
                    self._WHEEL_FRAME_MS, self._flush_wheel)
            except tk.TclError:
                self._wheel_flush_id = None
            pixels = applied
        try:
            self.canvas.yview_scroll(pixels, "units")
        except tk.TclError:
            pass

    def _attach_wheel(self, widget):
        try:
            tags = widget.bindtags()
            if self._scroll_tag not in tags:
                widget.bindtags((self._scroll_tag,) + tags)
        except tk.TclError:
            pass

    def attach_wheel(self, widget):
        """Public hook — call after adding new descendants if you want them
        to scroll the wheel too. No-op if already attached."""
        self._attach_wheel(widget)
        try:
            for child in widget.winfo_children():
                self.attach_wheel(child)
        except tk.TclError:
            pass


class VirtualizedCardList:
    """Lazy realize/derealize of card bodies based on scroll viewport.

    On Tk-on-Windows, every tk.Frame/Label/Button is a real Win32 HWND.
    A card-heavy panel ends up with hundreds of HWNDs inside the canvas;
    each scroll triggers a SetWindowPos for every visible child plus a
    canvas repaint. The OS can't always finish that inside one vsync
    interval, and the half-painted intermediate state is what shows up
    as "screen tearing" on the user's scroll wheel.

    This helper keeps each card's *body* container registered. When the
    body falls outside the viewport (with a generous overscan band so
    the user doesn't see flicker on small scroll moves), its children
    get destroyed and the body Frame is locked to its last known
    height. When the body re-enters the viewport, the supplied build
    function rebuilds the children. Net effect: only a handful of
    cards are fully realized at any moment, dramatically cutting the
    HWND count Tk has to reposition during scroll.

    Usage (caller already has a ScrollableFrame `sf`):

        virt = VirtualizedCardList(sf)
        # Per card:
        body = tk.Frame(card, ...)
        body.pack(fill="x")
        def _build(body_frame):
            ... build issue rows etc into body_frame ...
        _build(body)              # initial paint
        virt.register(body, _build)
        # On panel reset, clear before destroying widgets:
        virt.clear()

    Build functions MUST be idempotent — they're called every time the
    body re-enters the viewport. Persistent state (checkbox values,
    counters) must live outside the body or in shared modules
    (persistence, etc.). Locals captured by the build function on its
    first call become stale once children are destroyed; the rebuild
    creates fresh ones.
    """

    # While the user is actively scrolling, build/destroy of card-body
    # children causes a SetWindowPos burst that competes with the
    # canvas's own scroll repaint and shows up as tearing. Track when
    # the last scroll happened and only run realize/derealize once
    # scroll has been idle for this many ms — the user gets a smooth
    # tear-free scroll, and the catch-up rebuild happens during the
    # idle pause after they stop spinning the wheel.
    _SCROLL_IDLE_MS = 150

    def __init__(self, scrollable_frame, overscan_px=600):
        self.sf       = scrollable_frame
        self.canvas   = scrollable_frame.canvas
        self.cards    = []
        self.overscan_px = overscan_px
        self._update_after_id = None
        self._suspended = False
        self._last_scroll_ts = 0.0

        # Hook into yscrollcommand so we get a tick on every scroll.
        # The original command is the scrollbar's set() — preserve it.
        self._orig_yscrollcommand = self.canvas.cget("yscrollcommand")

        def _wrapped_scroll(*args):
            try:
                scrollable_frame.scrollbar.set(*args)
            except tk.TclError:
                pass
            self._last_scroll_ts = time.time()
            self._schedule_update()

        try:
            self.canvas.configure(yscrollcommand=_wrapped_scroll)
        except tk.TclError:
            pass

        # Resize → viewport changed → recheck visibility.
        try:
            self.canvas.bind("<Configure>",
                              lambda _e=None: self._schedule_update(),
                              add="+")
        except tk.TclError:
            pass

    def clear(self):
        """Drop all registered cards. Caller is responsible for
        destroying the underlying widgets (typically by destroying
        children of `inner`)."""
        self.cards = []
        if self._update_after_id is not None:
            try:
                self.canvas.after_cancel(self._update_after_id)
            except tk.TclError:
                pass
            self._update_after_id = None

    def register(self, body_frame, build_fn):
        """Register a card body as currently realized (caller has
        already called build_fn(body_frame) once). The virtualizer
        will derealize/re-realize on subsequent scroll events."""
        self.cards.append({
            "frame":          body_frame,
            "build":          build_fn,
            "realized":       True,
            "cached_height":  None,
        })
        self._schedule_update()

    def suspend(self):
        """Pause visibility ticks (e.g. during a render burst)."""
        self._suspended = True

    def resume(self):
        self._suspended = False
        self._schedule_update()

    def _schedule_update(self, _e=None):
        if self._suspended or self._update_after_id is not None:
            return
        try:
            # 60 ms tick: longer than the wheel coalesce (33 ms) so a
            # rapid scroll spin only fires one visibility pass per
            # ~2 wheel frames. We'd rather slightly over-realize
            # neighbors than thrash build/destroy on every notch.
            self._update_after_id = self.canvas.after(
                60, self._update_visibility)
        except tk.TclError:
            self._update_after_id = None

    def _update_visibility(self):
        self._update_after_id = None
        if self._suspended:
            return
        # Defer realize/derealize while the user is still scrolling.
        # Re-running build_fn / widget destruction during a scroll
        # burst is what causes tearing — wait for the wheel to go
        # idle, then catch up in one pass.
        elapsed_ms = (time.time() - self._last_scroll_ts) * 1000
        if elapsed_ms < self._SCROLL_IDLE_MS:
            wait = max(40, int(self._SCROLL_IDLE_MS - elapsed_ms + 10))
            try:
                self._update_after_id = self.canvas.after(
                    wait, self._update_visibility)
            except tk.TclError:
                pass
            return
        try:
            if not self.canvas.winfo_exists():
                return
            yview = self.canvas.yview()
            inner_h = self.sf.inner.winfo_height() or 1
            inner_rooty = self.sf.inner.winfo_rooty()
        except tk.TclError:
            return
        view_top = int(yview[0] * inner_h)
        view_bot = int(yview[1] * inner_h)
        band_top = view_top - self.overscan_px
        band_bot = view_bot + self.overscan_px

        for c in self.cards:
            try:
                if not c["frame"].winfo_exists():
                    continue
                # Unmapped frames (pack_forget'd when a tab is switched)
                # are off-screen by definition — derealize them so their
                # child HWNDs are freed while the tab is inactive, and
                # skip the position arithmetic entirely.
                if not c["frame"].winfo_ismapped():
                    if c["realized"]:
                        self._derealize(c)
                    continue
                # winfo_y is parent-relative; card bodies are nested
                # several frames deep, so use screen-absolute rooty
                # and subtract inner's rooty to get the body's
                # position in the inner-frame coordinate system —
                # which is the same space yview[]*inner_h lives in.
                y = c["frame"].winfo_rooty() - inner_rooty
                h = c["frame"].winfo_height()
                if h <= 1 and c["cached_height"]:
                    h = c["cached_height"]
            except tk.TclError:
                continue
            y2 = y + max(h, 1)
            in_band = (y2 >= band_top) and (y <= band_bot)
            if in_band and not c["realized"]:
                self._realize(c)
            elif not in_band and c["realized"]:
                self._derealize(c)

    def _realize(self, c):
        try:
            c["frame"].pack_propagate(True)
            try:
                c["frame"].configure(height=0)
            except tk.TclError:
                pass
            c["build"](c["frame"])
            c["realized"] = True
        except tk.TclError:
            pass

    def _derealize(self, c):
        try:
            c["frame"].update_idletasks()
            h = c["frame"].winfo_height()
            if h > 1:
                c["cached_height"] = h
                try:
                    c["frame"].configure(height=h)
                    c["frame"].pack_propagate(False)
                except tk.TclError:
                    pass
            for w in c["frame"].winfo_children():
                try:
                    w.destroy()
                except tk.TclError:
                    pass
            c["realized"] = False
        except tk.TclError:
            pass

    def is_frame_realized(self, frame):
        """Return True if the given frame is currently realized (has
        child widgets built). Returns True for unregistered frames so
        callers can safely skip the check when not using a virtualizer."""
        for c in self.cards:
            if c["frame"] is frame:
                return c["realized"]
        return True


# ── Toast notifications ─────────────────────────────────────────────────────
_TOAST_COLORS = {
    "info":    ("#E8F5EE", "#2C8C4D"),
    "success": ("#DAF1E2", "#007A3D"),
    "warning": ("#FFF4D6", "#A6772A"),
    "error":   ("#FBEAE5", "#C0392B"),
}


def show_toast(parent, message, kind="info", duration=2400):
    """Self-dismissing banner at the bottom of `parent`.

    Use for non-blocking confirmations ("Saved", "Folder created", "PDF
    generated"). For real errors that the user must acknowledge, use
    messagebox.showerror so they can't miss it.
    """
    bg, fg = _TOAST_COLORS.get(kind, _TOAST_COLORS["info"])
    toast = tk.Frame(parent, bg=bg, highlightbackground=fg, highlightthickness=1)
    tk.Label(toast, text=message, font=("Segoe UI Variable", 10),
             bg=bg, fg=fg, padx=18, pady=8).pack()
    toast.place(relx=0.5, rely=1.0, anchor="s", y=-14)
    toast.lift()

    def _kill():
        try:
            toast.destroy()
        except Exception:
            pass

    parent.after(duration, _kill)
    return toast


# ── Hover tooltips ─────────────────────────────────────────────────────────
#
# Shared tooltip helper. Multiple inline copies of this pattern existed
# across run_audit_gui.py / job_widgets / spreadsheet_gui — same Toplevel
# + Enter/Leave bindings + list-of-one ref trick each time. Consolidated
# here so every icon/badge/chip in the suite can opt in with one line:
#
#     from tool_panel import attach_tooltip
#     attach_tooltip(btn, "Open in Explorer")
#
# Tooltip pops a small dark Toplevel ~28px below the widget on hover,
# tears it down on Leave or ButtonPress. No third-party dep, no fancy
# styling — readable on every panel bg.

_TOOLTIP_MARKER = "_ems_has_tooltip"


# Icon → human-readable description. Used by `attach_default_tooltips`
# when a Button hasn't been given an explicit tooltip and its text
# starts with one of these glyphs — saves hand-labeling every icon
# button across the suite. Ordering matters when one prefix is a
# substring of another (e.g. "📥 SP" vs "📥") — longer prefixes win.
ICON_TOOLTIPS = {
    "📁":   "Open folder",
    "📂":   "Open",
    "📌":   "Pin Trello card",
    "📷":   "Photos",
    "📥":   "Import / download",
    "📨":   "Send",
    "💬":   "Open Teams message",
    "🗒":   "Job notes",
    "🚩":   "Escalate aging job",
    "🔄":   "Refresh / re-pull",
    "↻":    "Re-sync",
    "📄":   "Open document",
    "📅":   "Today",
    "📆":   "Date",
    "🏢":   "Franchise tag",
    "✓":    "Mark done",
    "×":    "Close / dismiss",
    "❓":   "Why? — diagnostic",
    "⏱":    "Extend SLA",
    "⏭":    "Skip",
    "✏":    "Edit",
    "⚠":    "Warning",
    "🗑":    "Delete",
    "📊":   "Stats / KPI",
    "🔎":   "Search / audit",
    "📋":   "Copy to clipboard",
    "📐":   "Docusketch",
    "📝":   "Notes / write",
    "🔔":   "Reminder",
    "🚨":   "Concern",
    "🏠":   "Home",
    "↗":    "Open external link",
    "🔍":   "Search",
    "⚙":    "Settings",
    "+":    "Add",
    "🚀":   "Intake",
    "✨":   "Highlight",
}


def _derive_default_tooltip(text):
    """Best-effort hover hint from a button's text. Returns None when
    the text is empty (no fallback worth showing).

    Lookup is longest-prefix-first so "📥 SP" still derives "Import /
    download — SP" instead of a partial match against just "📥". Pure
    icon buttons get the icon's human description; emoji+text buttons
    get "{description} — {text}". Buttons with plain text fall back to
    that text — repeating the label is mildly redundant but satisfies
    the "every button has a hover hint" rule.
    """
    t = (text or "").strip()
    if not t:
        return None
    # Sort icons by length descending so multi-char glyphs win first.
    for icon in sorted(ICON_TOOLTIPS.keys(), key=len, reverse=True):
        if t.startswith(icon):
            rest = t[len(icon):].strip().lstrip("-—·:|").strip()
            base = ICON_TOOLTIPS[icon]
            return f"{base} — {rest}" if rest else base
    return t


def attach_default_tooltips(parent):
    """Walk `parent`'s descendants and attach a default tooltip to any
    `tk.Button` that doesn't already have one. Pulls the hint from
    `ICON_TOOLTIPS` for emoji-prefixed buttons or falls back to the
    button's existing text.

    Idempotent — the per-widget `_TOOLTIP_MARKER` attribute prevents
    double-attaching. Safe to re-run after dynamic re-renders (audit
    card refresh, hygiene section rebuild) so newly-spawned buttons
    pick up tooltips without each call site remembering.

    Call once at the end of every panel's `_build_ui` (covers static
    chrome) and again after any large dynamic re-render of widgets
    that aren't already factory-built with `tooltip=`.
    """
    try:
        children = parent.winfo_children()
    except Exception:
        return
    for child in children:
        try:
            cls = child.winfo_class()
        except Exception:
            cls = ""
        if cls == "Button" and not getattr(child, _TOOLTIP_MARKER, False):
            try:
                text = child.cget("text")
            except Exception:
                text = ""
            tip = _derive_default_tooltip(text)
            if tip:
                attach_tooltip(child, tip)
        # Recurse regardless — Buttons can themselves contain children
        # (rare but legal in tk), and Frames hold the bulk of the tree.
        attach_default_tooltips(child)


def attach_tooltip(widget, text, *, delay_ms=350):
    """Bind a small hover tooltip to `widget`. `text` can be a string OR
    a zero-arg callable that returns the current text — use the callable
    form when the hint depends on dynamic row state (pin count, age,
    etc.) so the tooltip shows the LATEST value, not a snapshot from
    widget-creation time.

    `delay_ms` defaults to 350 — long enough that brushing the cursor
    across a row doesn't strobe a dozen tooltips, short enough that
    deliberate hover gets a near-instant answer.

    Returns the widget for chaining.
    """
    if widget is None:
        return widget
    # Mark the widget so `attach_default_tooltips` knows to leave it
    # alone on a later sweep. Set BEFORE bindings so duplicate calls
    # also no-op via the early-return below.
    if getattr(widget, _TOOLTIP_MARKER, False):
        return widget
    try:
        setattr(widget, _TOOLTIP_MARKER, True)
    except Exception:
        pass
    tip_state = {"win": None, "pending": None}

    def _resolve_text():
        try:
            return text() if callable(text) else text
        except Exception:
            return ""

    def _show():
        tip_state["pending"] = None
        msg = _resolve_text()
        if not msg:
            return
        if tip_state["win"] is not None:
            return
        try:
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except tk.TclError:
                pass
            from theme import SURFACE_2 as _SF2, TEXT_DARK as _TXD
            lbl = tk.Label(tw, text=msg,
                            font=("Segoe UI Variable", 8),
                            bg=_SF2, fg=_TXD,
                            padx=7, pady=3,
                            wraplength=260,
                            justify="left")
            lbl.pack()
            # Measure after pack so winfo_reqwidth/reqheight are accurate
            # before we place the toplevel.
            tw.update_idletasks()
            tip_w = tw.winfo_reqwidth()
            tip_h = tw.winfo_reqheight()
            # Constrain the tooltip to the app's top-level window bounds.
            # Toplevels otherwise float anywhere on the screen — if the
            # button is near the bottom edge of the app, the tooltip
            # spills below it and looks detached from the window.
            try:
                root = widget.winfo_toplevel()
                root.update_idletasks()
                root_x = root.winfo_rootx()
                root_y = root.winfo_rooty()
                root_w = root.winfo_width()
                root_h = root.winfo_height()
            except tk.TclError:
                root_x = root_y = 0
                root_w = root_h = 99999
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            wh = widget.winfo_height()
            # Default: tooltip 4px below the widget, nudged right by 4px.
            x = wx + 4
            y = wy + wh + 4
            # Flip above when below would clip the app window's bottom.
            if y + tip_h > root_y + root_h - 2:
                y = wy - tip_h - 4
                # If above also clips top, clamp inside the window.
                if y < root_y + 2:
                    y = root_y + 2
            # Shift left if right edge would clip the app window's right.
            if x + tip_w > root_x + root_w - 2:
                x = root_x + root_w - tip_w - 2
            # Final clamp on the left edge too.
            if x < root_x + 2:
                x = root_x + 2
            tw.wm_geometry(f"+{int(x)}+{int(y)}")
            tip_state["win"] = tw
        except tk.TclError:
            tip_state["win"] = None

    def _schedule_show(_e=None):
        _cancel_pending()
        try:
            tip_state["pending"] = widget.after(delay_ms, _show)
        except tk.TclError:
            tip_state["pending"] = None

    def _cancel_pending():
        p = tip_state["pending"]
        if p is not None:
            try:
                widget.after_cancel(p)
            except tk.TclError:
                pass
            tip_state["pending"] = None

    def _hide(_e=None):
        _cancel_pending()
        tw = tip_state["win"]
        if tw is not None:
            try:
                tw.destroy()
            except tk.TclError:
                pass
            tip_state["win"] = None

    widget.bind("<Enter>", _schedule_show, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")
    return widget


def attach_rich_tooltip(widget, builder, *, delay_ms=350, wrap_w=320):
    """Like `attach_tooltip` but the popover body is built by `builder(parent)`
    — a callable that fills a passed-in tk.Frame with whatever widgets it
    likes (labels, headings, chips, etc.). Use this when you need a
    structured hover popover instead of a plain text line.

    `builder` should return None; the popover sizes to the populated
    frame. The frame's parent is a Toplevel styled like the simple
    tooltip (SURFACE_2 bg + 1px border + topmost) so the rich popover
    visually matches the rest of the app's hover-tip language.

    Anything `builder` raises is swallowed — a failed hover should never
    take down the row that owns the button.
    """
    if widget is None or builder is None:
        return widget
    if getattr(widget, _TOOLTIP_MARKER, False):
        return widget
    try:
        setattr(widget, _TOOLTIP_MARKER, True)
    except Exception:
        pass
    tip_state = {"win": None, "pending": None}

    def _show():
        tip_state["pending"] = None
        if tip_state["win"] is not None:
            return
        try:
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except tk.TclError:
                pass
            from theme import SURFACE_2 as _SF2
            outer = tk.Frame(tw, bg=_SF2, padx=10, pady=8)
            outer.pack()
            try:
                builder(outer)
            except Exception:
                tw.destroy()
                return
            tw.update_idletasks()
            tip_w = tw.winfo_reqwidth()
            tip_h = tw.winfo_reqheight()
            try:
                root = widget.winfo_toplevel()
                root.update_idletasks()
                root_x = root.winfo_rootx()
                root_y = root.winfo_rooty()
                root_w = root.winfo_width()
                root_h = root.winfo_height()
            except tk.TclError:
                root_x = root_y = 0
                root_w = root_h = 99999
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            wh = widget.winfo_height()
            x = wx + 4
            y = wy + wh + 4
            if y + tip_h > root_y + root_h - 2:
                y = wy - tip_h - 4
                if y < root_y + 2:
                    y = root_y + 2
            if x + tip_w > root_x + root_w - 2:
                x = root_x + root_w - tip_w - 2
            if x < root_x + 2:
                x = root_x + 2
            tw.wm_geometry(f"+{int(x)}+{int(y)}")
            tip_state["win"] = tw
        except tk.TclError:
            tip_state["win"] = None

    def _schedule_show(_e=None):
        _cancel_pending()
        try:
            tip_state["pending"] = widget.after(delay_ms, _show)
        except tk.TclError:
            tip_state["pending"] = None

    def _cancel_pending():
        p = tip_state["pending"]
        if p is not None:
            try:
                widget.after_cancel(p)
            except tk.TclError:
                pass
            tip_state["pending"] = None

    def _hide(_e=None):
        _cancel_pending()
        tw = tip_state["win"]
        if tw is not None:
            try:
                tw.destroy()
            except tk.TclError:
                pass
            tip_state["win"] = None

    widget.bind("<Enter>", _schedule_show, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")
    return widget


# ── Error notification ──────────────────────────────────────────────────────
def notify_error(parent, source, message, fatal=False):
    """Centralized error path — always logs to ems.log; optionally shows
    a modal (fatal) or non-blocking toast (non-fatal)."""
    try:
        import ems_log
        ems_log.error(source, str(message))
    except Exception:
        pass
    try:
        if fatal:
            from tkinter import messagebox
            messagebox.showerror(source, str(message), parent=parent)
        else:
            show_toast(parent, str(message), kind="error", duration=3500)
    except Exception:
        pass


# ── Standalone wrapper ──────────────────────────────────────────────────────
def run_standalone(panel_class,
                   geometry="800x700",
                   minsize=None,
                   resizable=(True, True)):
    """Run `panel_class` as its own top-level window.

    If the class declares TOOL_GEOMETRY_KEY, the saved size/position
    overrides the `geometry` arg.
    """
    # Enable DPI awareness BEFORE creating the Tk root, then install
    # the widget scaler so font sizes + paddings get multiplied at
    # widget construction time. Both must happen before tk.Tk() is
    # called — see launcher.py for the same pattern. Idempotent: the
    # scaler short-circuits if already installed.
    try:
        import dpi_scaling as _dpi
        _dpi.enable_dpi_awareness()
        try:
            import config as _cfg_early
            _scale_from_cfg = _cfg_early.load().get("ui_scale")
            if _scale_from_cfg is None or str(_scale_from_cfg).lower() == "auto":
                _scale_from_cfg = 1.5
            _dpi.install_widget_scaler(float(_scale_from_cfg))
        except Exception:
            pass
    except Exception:
        _dpi = None

    aumid = getattr(panel_class, "TOOL_AUMID", None)
    if aumid:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(aumid)
        except Exception:
            pass

    saved_geo = None
    key = getattr(panel_class, "TOOL_GEOMETRY_KEY", None)
    if key:
        try:
            import persistence
            saved_geo = persistence.get_geometry(key)
        except Exception:
            saved_geo = None

    root = tk.Tk()
    # Apply DPI-matched widget scaling now that the root exists.
    if _dpi is not None:
        try:
            _dpi.apply_window_scaling(root)
        except Exception:
            pass
        # Ctrl + / Ctrl - / Ctrl 0 live scale adjustment — same UX as
        # the launcher so standalone tool windows are tunable too.
        def _on_scale_change(scale, _root=root):
            try:
                show_toast(_root,
                            f"UI scale: {scale:.2f}",
                            kind="info", duration=1400)
            except Exception:
                pass
        try:
            _dpi.bind_scale_shortcuts(root, on_change=_on_scale_change)
        except Exception:
            pass
    root.title(getattr(panel_class, "TOOL_TITLE", "EMS Tools"))
    root.geometry(saved_geo or geometry)
    if minsize:
        root.minsize(*minsize)
    root.resizable(*resizable)

    # Install before any tool / dialog is built so every Toplevel
    # popping up in this session lands centered + fit-to-content.
    try:
        install_auto_fit_handler(root)
    except Exception:
        pass

    icon = paths.resource("wrench.ico")
    if os.path.isfile(icon):
        try:
            root.iconbitmap(default=icon)
            root.iconbitmap(icon)
        except Exception:
            pass

    panel = panel_class(root)
    panel._embedded = False  # explicit
    panel.pack(fill="both", expand=True)
    panel.on_show()

    # Pop-out close fix: panels' _on_close callbacks call self.destroy(),
    # but on a tk.Frame that only tears down the frame — the Tk root window
    # stays visible and the window appears stuck. In standalone mode we
    # want self.destroy() to actually close the window, so wrap it to also
    # destroy the root. We patch the per-instance method (not the class)
    # so test fixtures sharing a Tk root aren't affected.
    _orig_destroy = panel.destroy

    def _close_window(*a, **kw):
        try:
            _orig_destroy(*a, **kw)
        except Exception:
            pass
        try:
            if root.winfo_exists():
                root.destroy()
        except Exception:
            pass

    panel.destroy = _close_window

    # Default WM_DELETE_WINDOW handler — only register if the panel didn't
    # already wire its own protocol callback during __init__ (which goes
    # through ToolPanel.protocol() and sets the toplevel handler). Without
    # this, panels that don't register protocol() leave the X button bound
    # to Tk's default destroy, which works — but we keep it explicit.
    if panel._on_close_cb is None:
        def _root_x_close():
            try:
                if root.winfo_exists():
                    root.destroy()
            except Exception:
                pass
        try:
            root.protocol("WM_DELETE_WINDOW", _root_x_close)
        except Exception:
            pass

    root.mainloop()
