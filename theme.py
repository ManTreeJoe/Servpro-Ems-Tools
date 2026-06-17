"""Shared UI color palette for all EMS Automation windows.

Two palettes live here — DARK (default) and LIGHT — both keyed on the
same constant names so importers don't change. `apply_appearance(mode)`
flips the module-level exports between them and also tells
customtkinter which appearance mode to use, so a single call
re-themes the entire app.

Modern Servpro green stays as the accent across both modes; only
the surfaces / text / borders move.
"""
from __future__ import annotations

# ── Palettes ─────────────────────────────────────────────────────────────────
# Each palette is a dict of constant→hex. apply_appearance copies the
# selected palette onto the module globals so `from theme import BG`
# works as it always has.

_DARK = {
    # "Espresso & Cream" — warm dark palette inspired by modern church
    # merch / Y2K bubble revival aesthetic (Hillsong, Drew House,
    # Art of Homage, CXXII). Warm umber surfaces instead of cool
    # near-black; cream text instead of cool white; sage accent
    # instead of saturated brand green.

    # Sage greens — desaturated, warmer than the corporate Servpro green
    "GREEN":         "#7DB892",   # sage
    "GREEN_DARK":    "#5F9974",   # forest sage
    "GREEN_LIGHT":   "#2D3A33",   # selected-row tint (dark sage)

    # Surfaces — three warm elevation levels
    "BG":            "#1C1815",   # warm espresso (window bg)
    "WHITE":         "#2A2520",   # warm umber "card" surface
    "SURFACE":       "#2A2520",
    "SURFACE_2":     "#332D27",   # one elevation up

    # Text — cream tones instead of cool whites
    "TEXT_DARK":     "#F4EDE1",   # cream
    "TEXT_GRAY":     "#B8AB97",   # warm taupe
    "TEXT_MUTED":    "#7A6F5F",

    # Lines — warm, subtle
    "BORDER":        "#3D362E",
    "BORDER_GRAY":   "#3D362E",

    # Accents — warm hues instead of cool primaries
    "FLAG_RED":      "#E08B7A",   # terracotta
    "WARN_AMBER":    "#D9A574",   # caramel
    "INFO_BLUE":     "#8FA7C2",   # dusty steel blue

    # Tinted action-button palette (bg / hover / fg triples)
    "SUCCESS_BG":    "#2D3A33",
    "SUCCESS_HOVER": "#384B40",
    "SUCCESS_FG":    "#A3D4B0",

    "INFO_BG":       "#2A3340",
    "INFO_HOVER":    "#354152",
    "INFO_FG":       "#B0C4DC",

    "LINK_BG":       "#2A3340",
    "LINK_HOVER":    "#354152",
    "LINK_FG":       "#B0C4DC",

    "WARN_BG":       "#3D2F1F",
    "WARN_HOVER":    "#4D3D28",
    "WARN_FG":       "#E6BC8C",

    "DANGER_BG":     "#3D2520",
    "DANGER_HOVER":  "#4D2F28",
    "DANGER_FG":     "#E8A493",

    "NEUTRAL_HOVER": "#332D27",

    # Always-light text for use on saturated accent backgrounds
    # (greens / purples / reds). Doesn't flip in dark mode — solid
    # accent buttons need light text in BOTH palettes for legibility.
    "ON_ACCENT": "#F4EDE1",
}

_LIGHT = {
    # "Sunday Morning" — warm cream-and-sage light palette to match
    # the dark side's church-merch vibe. Cream paper background
    # instead of cool clinical white.
    "GREEN":         "#5F9974",   # sage
    "GREEN_DARK":    "#3F7A56",   # forest sage
    "GREEN_LIGHT":   "#E6EFE7",   # tinted selected-row

    "WHITE":         "#FBF8F2",   # off-white card surface
    "BG":            "#F5EFE4",   # cream window bg
    "SURFACE":       "#FBF8F2",
    "SURFACE_2":     "#EFE8D8",

    "TEXT_DARK":     "#2D2620",   # warm near-black
    "TEXT_GRAY":     "#6B5F50",   # warm gray
    "TEXT_MUTED":    "#A89F8E",

    "BORDER":        "#D9CDB8",   # warm tan border
    "BORDER_GRAY":   "#D9CDB8",

    "FLAG_RED":      "#C16550",   # terracotta
    "WARN_AMBER":    "#B8853D",   # warm caramel
    "INFO_BLUE":     "#5A7896",   # dusty steel blue

    "SUCCESS_BG":    "#E6EFE7",
    "SUCCESS_HOVER": "#D5E5D8",
    "SUCCESS_FG":    "#3F7A56",

    "INFO_BG":       "#E5ECF2",
    "INFO_HOVER":    "#D4DEE8",
    "INFO_FG":       "#4A6580",

    "LINK_BG":       "#E5ECF2",
    "LINK_HOVER":    "#D4DEE8",
    "LINK_FG":       "#4A6580",

    "WARN_BG":       "#F5E4C9",
    "WARN_HOVER":    "#EDD7A8",
    "WARN_FG":       "#8C6529",

    "DANGER_BG":     "#F5DDD2",
    "DANGER_HOVER":  "#EDC9B8",
    "DANGER_FG":     "#A85040",

    "NEUTRAL_HOVER": "#EFE8D8",

    # Same purpose as in dark — always-light text for use on saturated
    # accent buttons. In light mode this stays near-white so any
    # solid colored button keeps its contrast.
    "ON_ACCENT": "#FBF8F2",
}


_PALETTES = {"dark": _DARK, "light": _LIGHT}

# ── Fonts ──────────────────────────────────────────────────────────────────
# Two-tier font system aligned with current fashion / streetwear trends:
#
#   FONT_FAMILY  → body text. Segoe UI Variable (Win11) for legibility at
#                  small sizes. Falls back to Segoe UI on Win10.
#   FONT_DISPLAY → headings, banners, big titles. Defaults to "Fraunces"
#                  (free Google Fonts variable serif — the bubble-retro
#                  serif you see on Drew House / Hillsong / Art of Homage
#                  merch). Auto-registered at startup via _register_bundled_fonts
#                  when fonts/Fraunces-*.ttf exists, otherwise falls back
#                  to "Georgia" — a built-in serif with bubble character
#                  so headings still look distinct from the body sans.
#
# To get the full bubble-retro look:
#   1. Download Fraunces (https://fonts.google.com/specimen/Fraunces) —
#      grab the static "Black" + "Bold" .ttf files OR the variable .ttf.
#   2. Drop them into `scripts/fonts/`.
#   3. Restart the launcher. _register_bundled_fonts loads them at run
#      time via Win32 AddFontResourceExW so they work even without
#      admin / system install.
FONT_FAMILY  = "Segoe UI Variable"
FONT_DISPLAY = "Fraunces"


def _register_bundled_fonts() -> None:
    """Register any .ttf / .otf files in scripts/fonts/ with Windows
    GDI at process scope, so Tk and CTk can use them without the user
    having to install fonts system-wide.

    Uses AddFontResourceExW with FR_PRIVATE so the registration:
      • Doesn't require admin rights
      • Doesn't pollute the system font list
      • Is automatically released when the process exits

    Silent no-op on non-Windows or when the fonts/ directory is empty
    — the FONT_DISPLAY value still resolves through Tk's font matcher
    (which substitutes Georgia / serif when Fraunces is unknown)."""
    import os as _os
    import sys as _sys
    if not _sys.platform.startswith("win"):
        return
    try:
        import ctypes
    except Exception:
        return
    here = _os.path.dirname(_os.path.abspath(__file__))
    fonts_dir = _os.path.join(here, "fonts")
    if not _os.path.isdir(fonts_dir):
        return
    FR_PRIVATE = 0x10
    # CRITICAL: use a fresh WinDLL handle, NOT `ctypes.windll.gdi32`.
    # Setting argtypes on the shared cached function pointer there
    # corrupts other libraries that use the same symbol — most
    # notably customtkinter's font manager which calls
    # AddFontResourceExW(byref(buf), …). A fresh WinDLL instance gives
    # us an isolated function-pointer cache so our argtypes don't
    # leak into CTk's call path.
    try:
        gdi32 = ctypes.WinDLL("gdi32")
        add_font = gdi32.AddFontResourceExW
        add_font.argtypes = (
            ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p)
        add_font.restype = ctypes.c_int
    except Exception:
        return
    for name in _os.listdir(fonts_dir):
        ext = _os.path.splitext(name)[1].lower()
        if ext not in (".ttf", ".otf"):
            continue
        path = _os.path.join(fonts_dir, name)
        try:
            add_font(path, FR_PRIVATE, None)
        except Exception:
            continue


# Fire once at import time — cheap (single os.listdir + per-file
# AddFontResourceExW), tolerates missing fonts/ dir.
_register_bundled_fonts()


def _install(palette: dict) -> None:
    """Copy palette values onto the module globals."""
    g = globals()
    for k, v in palette.items():
        g[k] = v


def current_mode() -> str:
    """Return 'dark' or 'light'. Reads the user's appearance setting
    from config.py (shared with the Settings dialog). 'system' resolves
    to dark if Windows is in dark mode, else light. Default is 'dark'
    when no setting is saved yet."""
    raw = "dark"
    try:
        import config as _cfg
        raw = (_cfg.load().get("appearance") or "dark").lower()
    except Exception:
        pass
    if raw == "system":
        # Best-effort: Windows AppsUseLightTheme=0 means dark.
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as k:
                v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
                return "light" if int(v) == 1 else "dark"
        except Exception:
            return "dark"
    return raw if raw in _PALETTES else "dark"


def apply_appearance(mode: str | None = None) -> str:
    """Switch the active palette + CTk appearance mode.

    Call once at app startup (with mode=None to read the user's saved
    preference) and again from a Settings toggle when the user
    changes it. Returns the resolved mode string."""
    if mode is None:
        mode = current_mode()
    mode = mode if mode in _PALETTES else "dark"
    _install(_PALETTES[mode])
    # Tell customtkinter to match. Lazy import — theme.py is imported
    # by modules that don't otherwise pull in CTk.
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("Dark" if mode == "dark" else "Light")
    except Exception:
        pass
    return mode


def set_mode(mode: str) -> None:
    """User-facing setter. Persists the choice via config.py (the same
    storage the Settings dialog writes to) and re-applies."""
    try:
        import config as _cfg
        cfg = _cfg.load()
        cfg["appearance"] = mode
        _cfg.save(cfg)
    except Exception:
        pass
    apply_appearance(mode)


def apply_ttk_theme(root) -> None:
    """Configure ttk widgets (Treeview, Combobox, Scrollbar, Spinbox,
    Notebook) to match the current palette.

    ttk widgets don't follow customtkinter's appearance mode — they
    inherit from the system ttk theme, which means a Treeview stays
    light-on-light in dark mode unless we explicitly restyle it.
    Call this once after the root window exists; safe to call again
    after `set_mode()` to re-theme on the fly."""
    try:
        from tkinter import ttk
    except Exception:
        return
    style = ttk.Style(root)
    # `clam` is the most-themable built-in; it lets us override fg/bg
    # on virtually every element (the default Windows theme refuses
    # to honor bg= on most widgets).
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Treeview — used by the Spreadsheets panel + a few dialogs.
    style.configure(
        "Treeview",
        background=WHITE,
        foreground=TEXT_DARK,
        fieldbackground=WHITE,
        borderwidth=0,
        rowheight=24,
        font=(FONT_FAMILY, 9))
    style.configure(
        "Treeview.Heading",
        background=SURFACE_2,
        foreground=TEXT_DARK,
        relief="flat",
        font=(FONT_FAMILY, 9, "bold"))
    style.map(
        "Treeview",
        background=[("selected", GREEN_LIGHT)],
        foreground=[("selected", TEXT_DARK)])
    style.map(
        "Treeview.Heading",
        background=[("active", SURFACE_2)])

    # Combobox — popdown list + entry both need restyle in dark mode.
    # `insertcolor` is the blinking text cursor inside the entry; without
    # it, dark mode renders a black caret on the dark surface and the
    # user can't see where they're typing.
    style.configure(
        "TCombobox",
        fieldbackground=WHITE,
        background=WHITE,
        foreground=TEXT_DARK,
        insertcolor=TEXT_DARK,
        bordercolor=BORDER,
        arrowcolor=TEXT_GRAY,
        lightcolor=BORDER,
        darkcolor=BORDER)
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", WHITE)],
        foreground=[("readonly", TEXT_DARK)],
        selectbackground=[("readonly", GREEN_LIGHT)],
        selectforeground=[("readonly", TEXT_DARK)])
    # The popdown listbox doesn't inherit from the style — patch it
    # via option_add so every new combobox picks up the dark colors.
    try:
        root.option_add("*TCombobox*Listbox.background", WHITE)
        root.option_add("*TCombobox*Listbox.foreground", TEXT_DARK)
        root.option_add("*TCombobox*Listbox.selectBackground", GREEN_LIGHT)
        root.option_add("*TCombobox*Listbox.selectForeground", TEXT_DARK)
        root.option_add("*TCombobox*Listbox.font",
                          (FONT_FAMILY, 9))
    except Exception:
        pass

    # Scrollbars
    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_2,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=TEXT_GRAY)
    style.configure(
        "Horizontal.TScrollbar",
        background=SURFACE_2,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=TEXT_GRAY)

    # Spinbox (year picker on Spreadsheets)
    style.configure(
        "TSpinbox",
        fieldbackground=WHITE,
        foreground=TEXT_DARK,
        bordercolor=BORDER,
        arrowcolor=TEXT_GRAY)

    # Entry (used inline by some dialogs)
    style.configure(
        "TEntry",
        fieldbackground=WHITE,
        foreground=TEXT_DARK,
        insertcolor=TEXT_DARK,
        bordercolor=BORDER)

    # tk.Text / tk.Listbox aren't ttk — they need per-widget settings
    # which we apply via the option DB so newly-created ones default
    # to the dark palette.
    try:
        root.option_add("*Text.background", WHITE)
        root.option_add("*Text.foreground", TEXT_DARK)
        root.option_add("*Text.insertBackground", TEXT_DARK)
        root.option_add("*Text.selectBackground", GREEN_LIGHT)
        root.option_add("*Text.selectForeground", TEXT_DARK)
        root.option_add("*Listbox.background", WHITE)
        root.option_add("*Listbox.foreground", TEXT_DARK)
        root.option_add("*Listbox.selectBackground", GREEN_LIGHT)
        root.option_add("*Listbox.selectForeground", TEXT_DARK)
        # tk.Entry defaults too
        root.option_add("*Entry.background", WHITE)
        root.option_add("*Entry.foreground", TEXT_DARK)
        root.option_add("*Entry.insertBackground", TEXT_DARK)
        root.option_add("*Entry.selectBackground", GREEN_LIGHT)
        root.option_add("*Entry.selectForeground", TEXT_DARK)
        # tk.Checkbutton / tk.Radiobutton — system default is black
        # text + a white indicator square, which renders as "black on
        # dark" + "invisible check mark" in dark mode. selectColor is
        # the indicator's fill when checked.
        root.option_add("*Checkbutton.foreground", TEXT_DARK)
        root.option_add("*Checkbutton.background", WHITE)
        root.option_add("*Checkbutton.activeForeground", TEXT_DARK)
        root.option_add("*Checkbutton.activeBackground", WHITE)
        root.option_add("*Checkbutton.selectColor", SURFACE_2)
        root.option_add("*Radiobutton.foreground", TEXT_DARK)
        root.option_add("*Radiobutton.background", WHITE)
        root.option_add("*Radiobutton.activeForeground", TEXT_DARK)
        root.option_add("*Radiobutton.activeBackground", WHITE)
        root.option_add("*Radiobutton.selectColor", SURFACE_2)
        # tk.Label / tk.Button — only set foreground; we don't want
        # to override per-widget bg overrides (theme buttons depend on
        # their kind-specific bg).
        root.option_add("*Label.foreground", TEXT_DARK)
        # tk.Menu (right-click context menus) — system default is
        # white-on-white on dark.
        root.option_add("*Menu.background", WHITE)
        root.option_add("*Menu.foreground", TEXT_DARK)
        root.option_add("*Menu.activeBackground", GREEN_LIGHT)
        root.option_add("*Menu.activeForeground", TEXT_DARK)
        root.option_add("*Menu.selectColor", TEXT_DARK)
    except Exception:
        pass


def style_tk_scrollbar(sb) -> None:
    """Apply current-palette colors to a legacy tk.Scrollbar.

    tk.Scrollbar predates ttk and ignores ttk.Style configuration, so each
    instance needs per-widget bg/troughcolor settings. Call right after
    construction. Safe to call on any widget; silently no-ops on errors."""
    try:
        sb.configure(
            bg=SURFACE_2,
            troughcolor=BG,
            activebackground=GREEN_DARK,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
        )
    except Exception:
        pass


# ── Spacing scale ──────────────────────────────────────────────────────────
# 4-point grid. Helium / Arc / Zen all anchor their spacing to a single
# multiple — every gap, padding, and inset is a number on this scale.
# Mixing 3/5/7/11 px gaps reads as "noisy" even when no one can
# articulate why; snapping to {4, 8, 12, 16, 24, 32} tightens visual
# rhythm without changing layouts dramatically.
#
# Use these tokens in new code. Legacy `pady=2, padx=6` callsites stay
# as-is — sweeping them is a separate pass.
SPACE_XS = 4    # tight pairing (icon ↔ text, chip cluster)
SPACE_S  = 8    # button cluster gap, row internal padding
SPACE_M  = 12   # row ↔ row, button ↔ button standard
SPACE_L  = 16   # section padding, dialog padding
SPACE_XL = 24   # major section gap, hero element breathing room
SPACE_2XL = 32  # page-level top/bottom margins


# ── Motion tokens ──────────────────────────────────────────────────────────
# Slow, confident transitions read as "premium". The 80ms default in
# most Tk apps reads as "snappy / cheap"; 150-200ms reads as "considered".
MOTION_FAST = 120   # toast appear, chip flicker
MOTION_BASE = 180   # hover transitions on buttons, link affordances
MOTION_SLOW = 280   # dialog fade-in/out, panel slide


# ── Color math ─────────────────────────────────────────────────────────────
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """Accept #rrggbb / #rgb hex codes. Falls back to a neutral gray
    for Tk-named colors (e.g. 'SystemButtonFace' on Windows) since
    color tweens require numeric channels. Returning a sensible
    fallback is safer than raising — a tween that lands on the wrong
    color is a visual nit; one that crashes a hover handler is a bug."""
    s = (h or "").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, IndexError):
        # Tk-named color or malformed string. Conservative fallback:
        # a near-white gray that interpolates cleanly toward any
        # plausible hover bg without producing wild color shifts.
        return (240, 240, 240)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def interp_color(a_hex: str, b_hex: str, t: float) -> str:
    """Linear-interpolate between two hex colors at t ∈ [0, 1]."""
    a = _hex_to_rgb(a_hex)
    b = _hex_to_rgb(b_hex)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def _ease_out_cubic(t: float) -> float:
    """Smooth deceleration — fast start, gentle settle. Matches the
    perceptual feel of Helium / Arc hover transitions better than
    linear (which reads as mechanical)."""
    inv = 1 - t
    return 1 - inv * inv * inv


# ── Color tween ────────────────────────────────────────────────────────────
def tween_color(widget, setter, from_hex: str, to_hex: str,
                 *, ms: int = MOTION_BASE, steps: int = 8,
                 token=None):
    """Animate `setter(color)` from from_hex → to_hex over ms milliseconds.

    `setter` is any callable taking one hex string. For a bg tween:
        tween_color(btn, lambda c: btn.configure(bg=c), '#fff', '#eee')
    For a canvas item:
        tween_color(c, lambda h: c.itemconfigure(id, fill=h), …)

    Returns a mutable list-token `[True]`. To cancel an in-flight
    tween (e.g. on rapid hover-out before hover-in finished), set
    `token[0] = False`. The next scheduled step will short-circuit.
    """
    if token is None:
        token = [True]
    n_steps = max(2, int(steps))
    interval = max(8, int(ms) // n_steps)

    def _step(i: int = 0):
        if not token[0]:
            return
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        if i >= n_steps:
            try:
                setter(to_hex)
            except Exception:
                pass
            return
        t = (i + 1) / n_steps
        eased = _ease_out_cubic(t)
        col = interp_color(from_hex, to_hex, eased)
        try:
            setter(col)
        except Exception:
            return
        try:
            widget.after(interval, lambda: _step(i + 1))
        except Exception:
            return

    _step(0)
    return token


def attach_hover_tween(widget, base_bg: str, hover_bg: str,
                        *, ms: int = MOTION_BASE,
                        base_fg: str | None = None,
                        hover_fg: str | None = None):
    """Bind <Enter> / <Leave> on `widget` so its background tweens
    smoothly between base_bg and hover_bg over `ms` milliseconds.
    Cancels an in-flight tween on rapid re-hover so the animation
    never "stutters past" the target color.

    Optionally also tweens the foreground color when hover_fg differs
    from base_fg (used by `link_button` for the underline-feel hover)."""
    state = {"current_bg": base_bg, "token_bg": None,
              "current_fg": base_fg, "token_fg": None}

    def _setter_bg(c, w=widget):
        try:
            w.configure(bg=c)
        except Exception:
            pass

    def _setter_fg(c, w=widget):
        try:
            w.configure(fg=c)
        except Exception:
            pass

    def _start(target_bg, target_fg):
        # Cancel in-flight bg tween, kick off new one.
        prev = state["token_bg"]
        if prev is not None:
            prev[0] = False
        from_bg = state["current_bg"]
        state["current_bg"] = target_bg
        state["token_bg"] = tween_color(
            widget, _setter_bg, from_bg, target_bg, ms=ms)
        if base_fg is not None and hover_fg is not None and base_fg != hover_fg:
            prev_fg = state["token_fg"]
            if prev_fg is not None:
                prev_fg[0] = False
            from_fg = state["current_fg"]
            state["current_fg"] = target_fg
            state["token_fg"] = tween_color(
                widget, _setter_fg, from_fg, target_fg, ms=ms)

    def _on_enter(_e=None):
        if state["current_bg"] != hover_bg:
            _start(hover_bg, hover_fg)

    def _on_leave(_e=None):
        if state["current_bg"] != base_bg:
            _start(base_bg, base_fg)

    try:
        widget.bind("<Enter>", _on_enter, add="+")
        widget.bind("<Leave>", _on_leave, add="+")
    except Exception:
        pass


def tween_alpha(top, from_a: float, to_a: float,
                 *, ms: int = MOTION_SLOW, steps: int = 10,
                 on_done=None):
    """Animate a Toplevel's window alpha (Win32 transparency). Used to
    fade dialogs in/out for the same "considered motion" feel hover
    tweens give buttons. Silently no-ops if the WM doesn't support
    `-alpha` (some Linux distros)."""
    n_steps = max(2, int(steps))
    interval = max(8, int(ms) // n_steps)

    def _step(i: int = 0):
        try:
            if not top.winfo_exists():
                return
        except Exception:
            return
        if i >= n_steps:
            try:
                top.attributes("-alpha", to_a)
            except Exception:
                pass
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            return
        t = (i + 1) / n_steps
        eased = _ease_out_cubic(t)
        a = from_a + (to_a - from_a) * eased
        try:
            top.attributes("-alpha", a)
        except Exception:
            return
        try:
            top.after(interval, lambda: _step(i + 1))
        except Exception:
            return

    _step(0)


def fade_in_toplevel(top, *, ms: int = MOTION_SLOW):
    """Start a Toplevel invisible and tween it to opaque. Call before
    .deiconify() / .grab_set() to get the fade-in effect."""
    try:
        top.attributes("-alpha", 0.0)
    except Exception:
        return
    tween_alpha(top, 0.0, 1.0, ms=ms)


# Install the active palette at import time so plain `from theme import BG`
# returns the right value before any explicit call to apply_appearance.
apply_appearance()
