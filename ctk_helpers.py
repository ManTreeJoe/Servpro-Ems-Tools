"""Shared CTk widget factories + "feels-fast" UX helpers.

Goal: every panel uses the same widgets, same spacing, same hover/loading
behavior — without each one re-importing customtkinter and re-deriving the
same kwargs. Also a small set of perf tricks (debounce, deferred render,
busy-cursor) the panels lean on to feel snappy without doing real
work in the background.

CTk is a hard dependency now (requirements.txt). If it's missing, this
module raises at import time so callers don't silently degrade to plain
tk — that was the source of inconsistent look between dev installs.
"""
import os
import tkinter as tk

import customtkinter as ctk

from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                   BORDER, FLAG_RED, SURFACE_2, NEUTRAL_HOVER,
                   SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
                   INFO_BG, INFO_FG, INFO_HOVER,
                   WARN_BG, WARN_FG, WARN_HOVER,
                   DANGER_BG, DANGER_FG, DANGER_HOVER,
                   ON_ACCENT)


# ── Spacing / sizing tokens ──────────────────────────────────────────────────
# Single source of truth so every panel feels the same. Bumped from the
# initial pass — slightly more breathing room everywhere makes the app
# feel less cramped without making the layout feel sparse.
PAD_XS = 4
PAD_S  = 10
PAD_M  = 14
PAD_L  = 20
PAD_XL = 28
# Bubble / retro radius — pushed further for the chunky Y2K-bubble
# feel the user asked for. Buttons and cards now read as soft pills.
# Per the Espresso & Cream aesthetic pass (2026-05-15).
RADIUS = 18
RADIUS_SM = 14
RADIUS_LG = 24
ROW_H  = 38   # standard interactive-row height
BTN_H  = 38   # standard button height — chunkier
BTN_H_LG = 44 # primary CTA height
HEADER_H = 58 # green strip header height

# Re-export the theme's font tokens so panels can pull from one place.
# theme._register_bundled_fonts() ran at theme import, so by the time
# we get here Fraunces (if bundled) is already registered with GDI.
import theme as _theme
FONT_FAMILY  = _theme.FONT_FAMILY      # body — Segoe UI Variable
FONT_DISPLAY = _theme.FONT_DISPLAY     # headings — Fraunces (fallback Georgia)

# Tell customtkinter which appearance mode to match. This lives HERE, not
# at the bottom of theme.py, because theme is imported by web panels that
# never create a widget — running it there dragged tkinter, customtkinter
# and PIL into every one of them. This module already imports CTk and is
# imported by every Tk panel and by nothing else, so it is the right home
# for the Tk half of the theme.
_theme.apply_appearance()


def font(size=10, weight="normal"):
    """Build a CTkFont for body text. Centralized so panels can't
    drift on family/size."""
    return ctk.CTkFont(FONT_FAMILY, size, weight)


def display_font(size=14, weight="bold"):
    """Build a CTkFont for headings / banners using the display family.
    Tk's font matcher silently substitutes when Fraunces isn't
    registered — Georgia is the configured fallback in theme."""
    return ctk.CTkFont(FONT_DISPLAY, size, weight)


# ── Widget factories ─────────────────────────────────────────────────────────
def card(parent, **kw):
    """Bordered, rounded container — the standard 'panel' look.

    Per the Espresso & Cream pass we drop the 1px border in favour of
    surface-elevation contrast: the card sits in a `WHITE` umber tone
    on a `BG` espresso background, creating a soft visible step
    without a hard outline. Callers can still opt back into a border
    by passing `border_width=1` explicitly."""
    kw.setdefault("fg_color", WHITE)
    kw.setdefault("corner_radius", RADIUS)
    kw.setdefault("border_width", 0)
    return ctk.CTkFrame(parent, **kw)


def toolbar(parent, **kw):
    """Slim horizontal frame that hosts action buttons. No border, light bg."""
    kw.setdefault("fg_color", BG)
    kw.setdefault("corner_radius", 0)
    kw.setdefault("height", ROW_H + 8)
    return ctk.CTkFrame(parent, **kw)


def header_strip(parent, title, subtitle=None, color=GREEN):
    """Branded header band — green strip with white title/subtitle.
    Used at the top of standalone panels (not embedded ones). Title
    uses the display font (Fraunces) so the brand strip carries the
    retro / bubble-serif vibe; subtitle stays in the body sans for
    legibility."""
    h = ctk.CTkFrame(parent, fg_color=color, corner_radius=0,
                     height=58 if subtitle else 38)
    h.pack(fill="x")
    h.pack_propagate(False)
    ctk.CTkLabel(h, text=title, font=display_font(16, "bold"),
                 text_color=WHITE).pack(pady=(8 if subtitle else 6, 0))
    if subtitle:
        ctk.CTkLabel(h, text=subtitle, font=font(9),
                     text_color="#B2DFC4").pack(pady=(0, 6))
    return h


def h1(parent, text, **kw):
    # h1 uses the display font (Fraunces, retro-bubble serif) so
    # top-of-panel titles read as branded display copy, distinct from
    # the body sans.
    kw.setdefault("font", display_font(15, "bold"))
    kw.setdefault("text_color", TEXT_DARK)
    return ctk.CTkLabel(parent, text=text, **kw)


def h2(parent, text, **kw):
    kw.setdefault("font", font(11, "bold"))
    kw.setdefault("text_color", TEXT_DARK)
    return ctk.CTkLabel(parent, text=text, **kw)


def hint(parent, text, **kw):
    """Subdued text — used for help captions under inputs."""
    kw.setdefault("font", font(9))
    kw.setdefault("text_color", TEXT_GRAY)
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    return ctk.CTkLabel(parent, text=text, **kw)


def _btn_kinds():
    """Lazy-eval the button-kind palette so it picks up the current theme
    mode at button-creation time, not at module import.
    Theme tokens are module-level globals in `theme`; they get swapped
    when the user toggles dark/light, so re-reading here keeps colors
    in sync after a runtime theme change."""
    return {
        # primary: sage green, cream text — main action on the screen
        "primary": dict(fg_color=GREEN, hover_color=GREEN_DARK,
                        text_color=ON_ACCENT),
        # ghost: faint elevated chip — secondary actions. We use
        # SURFACE_2 (one elevation above the panel BG) rather than
        # transparent so the button is visible on dark mode against
        # the warm-espresso panel bg; the 1px border kept the chip
        # legible in light mode but disappeared in dark when the
        # border + bg + transparent fill all blurred together. With
        # a real fill we get a button that reads as a chip in both
        # modes without losing the "quiet secondary action" feel.
        "ghost":   dict(fg_color=SURFACE_2, hover_color=NEUTRAL_HOVER,
                        text_color=TEXT_DARK, border_width=0),
        # subtle: tinted surface — rest reads as pale chip, hover lifts
        "subtle":  dict(fg_color=SUCCESS_BG, hover_color=SUCCESS_HOVER,
                        text_color=SUCCESS_FG),
        # info: blue-tinted soft chip
        "info":    dict(fg_color=INFO_BG, hover_color=INFO_HOVER,
                        text_color=INFO_FG),
        # warn: amber chip
        "warn":    dict(fg_color=WARN_BG, hover_color=WARN_HOVER,
                        text_color=WARN_FG),
        # danger: red — destructive actions only
        "danger":  dict(fg_color=FLAG_RED, hover_color=DANGER_HOVER,
                        text_color=ON_ACCENT),
    }


def btn(parent, text, command=None, kind="primary", **kw):
    """Themed bubble button. `kind` is one of:
    primary, ghost, subtle, info, warn, danger."""
    defaults = _btn_kinds().get(kind, _btn_kinds()["primary"])
    for k, v in defaults.items():
        kw.setdefault(k, v)
    kw.setdefault("font", font(11, "bold"))
    kw.setdefault("height", BTN_H)
    # Use the larger RADIUS so buttons read as soft pills rather than
    # mildly-rounded rectangles — the bubble-retro look the user asked
    # for (Hillsong/Drew House merch aesthetic).
    kw.setdefault("corner_radius", RADIUS)
    kw.setdefault("cursor", "hand2")
    return ctk.CTkButton(parent, text=text, command=command, **kw)


def entry(parent, **kw):
    kw.setdefault("font", font(10))
    kw.setdefault("height", BTN_H)
    kw.setdefault("corner_radius", RADIUS)
    kw.setdefault("border_width", 1)
    kw.setdefault("border_color", BORDER)
    return ctk.CTkEntry(parent, **kw)


def combobox(parent, values, **kw):
    """Read-only dropdown."""
    kw.setdefault("values", list(values))
    kw.setdefault("state", "readonly")
    kw.setdefault("font", font(10))
    kw.setdefault("height", BTN_H)
    kw.setdefault("corner_radius", RADIUS)
    kw.setdefault("border_width", 1)
    kw.setdefault("border_color", BORDER)
    kw.setdefault("button_color", GREEN)
    kw.setdefault("button_hover_color", GREEN_DARK)
    return ctk.CTkComboBox(parent, **kw)


def switch(parent, text, variable, **kw):
    kw.setdefault("font", font(10))
    kw.setdefault("text_color", TEXT_DARK)
    kw.setdefault("progress_color", GREEN)
    kw.setdefault("button_color", WHITE)
    kw.setdefault("button_hover_color", NEUTRAL_HOVER)
    return ctk.CTkSwitch(parent, text=text, variable=variable, **kw)


def scrollable(parent, **kw):
    """CTkScrollableFrame with the Servpro green scrollbar accent."""
    kw.setdefault("fg_color", WHITE)
    kw.setdefault("corner_radius", 0)
    kw.setdefault("scrollbar_button_color", GREEN)
    kw.setdefault("scrollbar_button_hover_color", GREEN_DARK)
    return ctk.CTkScrollableFrame(parent, **kw)


def divider(parent, **kw):
    kw.setdefault("fg_color", BORDER)
    kw.setdefault("height", 1)
    kw.setdefault("corner_radius", 0)
    return ctk.CTkFrame(parent, **kw)


# ── "Feels fast" UX helpers ──────────────────────────────────────────────────
class Debouncer:
    """Coalesces rapid calls into one callback after `delay_ms` of quiet.

    Used for search-as-you-type and other input-driven re-renders so we
    don't repaint the world on every keystroke. Cancels prior pending
    callback when re-fired.

        deb = Debouncer(panel, 200)
        var.trace_add("write", lambda *_: deb.fire(do_search))
    """
    def __init__(self, widget, delay_ms=250):
        self._w = widget
        self._delay = delay_ms
        self._pending = None

    def fire(self, callback):
        if self._pending is not None:
            try:
                self._w.after_cancel(self._pending)
            except Exception:
                pass
        self._pending = self._w.after(self._delay, callback)

    def cancel(self):
        if self._pending is not None:
            try:
                self._w.after_cancel(self._pending)
            except Exception:
                pass
            self._pending = None


def busy_cursor(widget, work_fn):
    """Show wait-cursor while `work_fn()` runs; restore after.
    Prefer for synchronous ops <500ms; longer ops belong on a thread."""
    try:
        widget.configure(cursor="watch")
        widget.update_idletasks()
    except Exception:
        pass
    try:
        return work_fn()
    finally:
        try:
            widget.configure(cursor="")
        except Exception:
            pass


def defer(widget, fn, ms=1):
    """Run `fn` after the current event loop finishes painting.
    Use for the tail of an init that doesn't need to block first paint
    (e.g. focus calls, autoscroll, expensive layout polish)."""
    try:
        return widget.after(ms, fn)
    except Exception:
        try:
            fn()
        except Exception:
            pass


# ── Overflow menu (kebab) ────────────────────────────────────────────────────
class MoreMenu:
    """A '⋯ More' button that pops up a menu of secondary actions.

    Modern apps hide rarely-used buttons behind a kebab/More menu so the
    primary action bar stays focused. Usage:

        more = MoreMenu(parent, label="⋯")
        more.add("Open in Notepad", command=self._open_in_notepad)
        more.add("Reload", command=self._reload)
        more.add_separator()
        more.add("Reset to defaults", command=self._reset, danger=True)
        more.button.pack(side="right", padx=4)

    Items are appended to a tk.Menu (CTk has no native menu widget — a
    plain tk.Menu blends fine since it inherits the OS theme).
    """
    def __init__(self, parent, label="⋯ More", width=90, kind="ghost"):
        self._parent = parent
        self._menu = tk.Menu(parent, tearoff=0,
                             bg=WHITE, fg=TEXT_DARK,
                             activebackground=GREEN, activeforeground=WHITE,
                             font=(FONT_FAMILY, 10),
                             borderwidth=1, relief="solid")
        self.button = btn(parent, label, command=self._popup,
                          kind=kind, width=width)

    def add(self, label, command, danger=False, icon=None):
        text = f"{icon}  {label}" if icon else label
        if danger:
            self._menu.add_command(
                label=text, command=command,
                foreground=FLAG_RED, activeforeground=WHITE,
                activebackground=FLAG_RED)
        else:
            self._menu.add_command(label=text, command=command)
        return self

    def add_separator(self):
        self._menu.add_separator()
        return self

    def _popup(self):
        try:
            x = self.button.winfo_rootx()
            y = self.button.winfo_rooty() + self.button.winfo_height()
            self._menu.tk_popup(x, y)
        finally:
            self._menu.grab_release()


def chip(parent, text, kind="default", **kw):
    """Pill-shaped status badge — replaces the manual padded-Label idiom
    for badges/tags. `kind` ∈ {default, success, warn, danger, info,
    accent}. Theme-aware: re-reads the palette at call time so it
    flips correctly on dark/light toggle.

    Full corner_radius makes it a true pill (no almost-pill look) and
    a slightly taller `height` (26 vs 22) reads chunkier — matches the
    bubble button bump."""
    palette = {
        "default": (SURFACE_2,     TEXT_GRAY),
        "success": (SUCCESS_HOVER, SUCCESS_FG),
        "warn":    (WARN_HOVER,    WARN_FG),
        "danger":  (DANGER_HOVER,  FLAG_RED),
        "info":    (INFO_HOVER,    INFO_FG),
        "accent":  (GREEN,         ON_ACCENT),
    }
    bg, fg = palette.get(kind, palette["default"])
    kw.setdefault("text", text)
    kw.setdefault("font", font(9, "bold"))
    kw.setdefault("text_color", fg)
    kw.setdefault("fg_color", bg)
    kw.setdefault("corner_radius", 999)  # full pill
    kw.setdefault("height", 26)
    # CTkLabel doesn't accept padx — drop it if a caller passed it
    # along with the old padx-based pattern.
    kw.pop("padx", None)
    lbl = ctk.CTkLabel(parent, **kw)
    return lbl


