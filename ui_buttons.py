"""Shared button factories for the Linguar Hub.

Every tool with row-level actions (Audit, Initial Upload, Snapshot,
Hygiene, APA Monitor, Daily Photos, SP Recent) renders buttons that
play the same semantic role — "Send", "Done/Resolved", "Skip/Dismiss",
"Open email", "Open OD folder", "Trello card". Until now each tool
constructed those `tk.Button(...)` calls inline with subtly different
padding, fg/bg colors, and fonts. Three tools said `relief="solid"
bd=1` for outline buttons; one said `relief="flat"`. Two used
`TEXT_DARK`; the third used `TEXT_GRAY`. Same role, three looks.

The factories below are the single source of truth for the button
styles in the suite. Pick the factory whose name matches the action's
semantic role; the visual shape follows automatically.

    from ui_buttons import send_button, done_button, secondary_button

    send_button(parent, "📋 Send 48h ack",
                command=lambda r=req: self._send_ack(r)
                ).pack(side="right", padx=(0, 6))
    done_button(parent, "✓ Resolved",
                command=lambda g=group: self._resolve(g)
                ).pack(side="right", padx=(0, 6))

Each factory returns a RoundedButton (a tk.Label dressed up with a
PIL-rendered anti-aliased rounded-rect background image and hover-
tweened color). The return is API-compatible with tk.Button for the
methods the EMS suite uses (.config/.cget/.bind/.pack/.grid/.destroy).

Design philosophy borrowed from Helium / Arc / Zen:
    • Pill shape — radius auto-derived from height so buttons read as
      capsules. Override via radius= when something needs sharper corners.
    • Hover transitions are 180ms ease-out cubic, not 0ms. Reads as
      "considered" instead of "snappy".
    • Press state darkens the current bg by ~15% (interpolated against
      black) for a tactile click acknowledgement.
    • Cursor is `hand2` so the OS confirms the interactivity.
"""
from __future__ import annotations

import tkinter as tk

from theme import (
    BG, WHITE, TEXT_DARK, TEXT_GRAY, FONT_FAMILY,
    SUCCESS_BG, SUCCESS_HOVER, SUCCESS_FG,
    INFO_BG, INFO_HOVER, INFO_FG,
    LINK_BG, LINK_HOVER, LINK_FG,
    WARN_BG, WARN_HOVER, WARN_FG,
    DANGER_BG, DANGER_HOVER, DANGER_FG,
    NEUTRAL_HOVER, SURFACE_2, FLAG_RED,
    MOTION_BASE,
    tween_color, interp_color,
)


# Bubble-retro sizing pass: bumped vertical padding and font weight
# so action buttons read as chunky pills instead of skinny flat strips.
# Segoe UI Variable picks up the slightly heavier "Display" axis on
# Windows 11 at 9pt; on 8pt the metrics flip to "Text" which is the
# old skinny look we're moving away from.
_DEFAULT_FONT_BOLD = (FONT_FAMILY, 9, "bold")
_DEFAULT_FONT      = (FONT_FAMILY, 9)
_DEFAULT_PADX      = 12
_DEFAULT_PADY      = 5
_DEFAULT_RADIUS    = 10
_PILL_RADIUS_CAP   = 16  # Hard cap so very tall buttons don't go disc-shaped.


# ── Rounded-rect image cache ───────────────────────────────────────────────
# PIL renders a supersampled antialiased rounded rectangle once per
# (w, h, bg_hex, radius) combo; subsequent buttons sharing the same
# style + dimensions reuse the cached PhotoImage instantly. Strong
# refs live in the cache dict so the images survive their owning
# widgets' destruction — Tk silently drops images whose last Python
# reference dies, which would render buttons as blank rectangles.

class _RoundedRectCache:
    """Module-level (w, h, bg_hex, radius) → ImageTk.PhotoImage cache."""

    _cache: dict = {}
    _pil_available: bool | None = None

    @classmethod
    def _have_pil(cls):
        if cls._pil_available is not None:
            return cls._pil_available
        try:
            from PIL import Image, ImageDraw, ImageTk  # noqa: F401
            cls._pil_available = True
        except ImportError:
            cls._pil_available = False
        return cls._pil_available

    @classmethod
    def get(cls, w: int, h: int, bg_hex: str, radius: int):
        """Return the cached PhotoImage, generating it lazily on first
        request. Returns None when PIL is unavailable or Tk isn't ready
        — callers fall back to a flat-color background."""
        if w <= 0 or h <= 0:
            return None
        key = (int(w), int(h), bg_hex.lower(), int(radius))
        cached = cls._cache.get(key)
        if cached is not None:
            return cached
        if not cls._have_pil():
            return None
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            return None
        # Supersample 2× for cleaner antialiased corners, then downscale.
        scale = 2
        ww, hh = w * scale, h * scale
        rr = max(0, min(radius * scale, min(ww, hh) // 2))
        try:
            img = Image.new("RGBA", (ww, hh), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle(
                (0, 0, ww - 1, hh - 1), radius=rr, fill=bg_hex)
            img = img.resize((w, h), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
        except Exception:
            return None
        cls._cache[key] = tk_img
        return tk_img


class RoundedButton(tk.Label):
    """tk.Label dressed up as a button.

    Visual:
        • Anti-aliased rounded-rect background from a cached PhotoImage.
        • Text overlaid at center via `compound="center"`.
        • Hover transitions are color-tweened over MOTION_BASE ms with
          ease-out-cubic.
        • Press state darkens the current bg ~15% for a brief tactile flash.

    API:
        Drop-in replacement for `tk.Button` for the methods the EMS
        suite actually uses: .config/.cget/.bind/.pack/.grid/.place/
        .pack_forget/.destroy. Reads text/bg/fg/state/command through
        the standard tkinter Option DB.

    Falls back to a plain flat-color Label when PIL isn't available —
    so the suite still runs on a stripped-down deploy that skipped Pillow.
    """

    def __init__(self, parent, text: str = "", *,
                 bg: str, fg: str, hover_bg: str,
                 hover_fg: str | None = None,
                 font=None, padx: int = _DEFAULT_PADX, pady: int = _DEFAULT_PADY,
                 radius: int = _DEFAULT_RADIUS,
                 command=None, state: str = "normal"):
        # The Label's actual bg matches the parent's so the rounded
        # corners blend into the surrounding surface seamlessly. Setting
        # Label bg=bg would leave 4 little squared shoulders at each corner.
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG
        font = font or _DEFAULT_FONT_BOLD
        super().__init__(parent, text=text, font=font, fg=fg,
                          bg=parent_bg, bd=0, highlightthickness=0,
                          cursor="hand2", padx=0, pady=0)
        self._text     = text
        self._font     = font
        self._bg       = bg
        self._fg       = fg
        self._hover_bg = hover_bg
        self._hover_fg = hover_fg or fg
        self._padx     = padx
        self._pady     = pady
        self._radius   = radius
        self._command  = command or (lambda: None)
        self._state    = state
        self._current_bg = bg
        self._current_image = None
        self._tween_token = None
        self._fg_tween_token = None
        self._press_armed = False

        # First geometry + image
        self._refresh_image()

        # Mouse bindings
        self.bind("<Enter>",         self._on_enter, add="+")
        self.bind("<Leave>",         self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")

        if state == "disabled":
            self._apply_disabled_style()

    # ── geometry ──────────────────────────────────────────────────────────
    def _measure(self) -> tuple[int, int]:
        """Return (width, height) of the desired pill, accounting for
        text size + this button's padding tokens.

        IMPORTANT: do NOT use ``winfo_reqwidth()`` here. After the
        first ``_refresh_image`` we set a PhotoImage on the label with
        ``compound="center"``, which makes Tk's reqwidth return the
        max of (image-width, text-width). Subsequent text changes
        re-trigger _measure → reqwidth now reads the EXISTING image's
        width, then we add padx*2 again to make a new image that's
        +padx*2 wider than the last, and so on. End result: the
        button grew by padx*2 pixels on every ``.configure(text=...)``
        call (Re-scan button in Hygiene was the loud reporter).

        Solution: measure the text via tkfont.Font directly, which is
        independent of whatever image is currently on the label.
        """
        try:
            from tkinter import font as tkfont
            f = tkfont.Font(font=self._font)
            tw = f.measure(self._text or " ")
            th = f.metrics("linespace")
        except Exception:
            # Heuristic fallback on stripped-down deployments where
            # tkfont isn't usable yet. Better than 0 — at least the
            # button renders.
            tw, th = max(40, len(self._text or "") * 7), 18
        return tw + self._padx * 2, th + self._pady * 2

    def _refresh_image(self):
        w, h = self._measure()
        self._pill_w, self._pill_h = w, h
        # Cap pill radius to half-height so taller buttons stay pills
        # without going full-circle on the corners.
        eff_radius = min(self._radius, max(2, h // 2), _PILL_RADIUS_CAP)
        self._eff_radius = eff_radius
        self._set_image_for_bg(self._current_bg)

    def _set_image_for_bg(self, color: str):
        """Repaint the rounded backdrop in `color`. Bypasses our own
        .configure() override and goes straight to tk.Label.configure
        because the kwargs we're setting here (image, compound, and the
        label's actual bg=parent_bg-for-corners) are internal-only —
        they would otherwise recurse back through the override and
        clobber `self._bg` / `self._current_bg` semantics.

        When `_external_image` is True (caller set `image=` via
        configure), DO NOT overwrite the image — the user wants their
        custom image visible. Only tween the Label's bg so hover state
        is still felt; if the caller wants a richer hover they can
        bind <Enter>/<Leave> themselves."""
        if getattr(self, "_external_image", False):
            try:
                tk.Label.configure(self, background=color)
            except Exception:
                pass
            return
        img = _RoundedRectCache.get(
            self._pill_w, self._pill_h, color, self._eff_radius)
        if img is None:
            # PIL fell over or Tk root isn't ready — flat color fallback.
            try:
                tk.Label.configure(self, image="", background=color)
            except Exception:
                pass
            return
        try:
            parent_bg = self.master.cget("bg") if hasattr(self.master, "cget") else BG
        except Exception:
            parent_bg = BG
        try:
            tk.Label.configure(self, image=img,
                                 compound="center", background=parent_bg)
        except Exception:
            return
        self._current_image = img

    # ── hover / press ─────────────────────────────────────────────────────
    def _on_enter(self, _e=None):
        if self._state == "disabled":
            return
        if self._current_bg == self._hover_bg:
            return
        self._start_tween(self._hover_bg, self._hover_fg)

    def _on_leave(self, _e=None):
        if self._state == "disabled":
            return
        self._press_armed = False
        if self._current_bg == self._bg:
            return
        self._start_tween(self._bg, self._fg)

    def _start_tween(self, target_bg: str, target_fg: str):
        if self._tween_token is not None:
            self._tween_token[0] = False
        from_bg = self._current_bg
        self._current_bg = target_bg

        def _setter(c, self=self):
            self._set_image_for_bg(c)

        self._tween_token = tween_color(
            self, _setter, from_bg, target_bg, ms=MOTION_BASE, steps=6)

        # Foreground tween — only when hover_fg differs from base fg
        # (rare; only the link variant uses this today).
        if self._fg != self._hover_fg:
            if self._fg_tween_token is not None:
                self._fg_tween_token[0] = False
            from_fg = (self._hover_fg
                        if target_fg == self._fg else self._fg)
            def _fg_setter(c, self=self):
                try:
                    super(RoundedButton, self).configure(fg=c)
                except Exception:
                    pass
            self._fg_tween_token = tween_color(
                self, _fg_setter, from_fg, target_fg,
                ms=MOTION_BASE, steps=6)

    def _on_press(self, _e=None):
        if self._state == "disabled":
            return
        self._press_armed = True
        # Tactile darken — interpolate the current bg 15% toward black
        # for the press-down flash. _on_release restores the hover bg.
        press_bg = interp_color(self._current_bg, "#000000", 0.15)
        self._set_image_for_bg(press_bg)

    def _on_release(self, _e=None):
        if self._state == "disabled":
            return
        was_armed = self._press_armed
        self._press_armed = False
        # Restore visual state to whatever the hover state should be.
        self._set_image_for_bg(self._current_bg)
        if was_armed:
            try:
                self._command()
            except Exception:
                pass

    def _apply_disabled_style(self):
        try:
            tk.Label.configure(self, cursor="arrow", foreground=TEXT_GRAY)
        except Exception:
            pass

    # ── tk.Button-compatible API ─────────────────────────────────────────
    def configure(self, cnf=None, **kw):
        """Re-implements the subset of tk.Button.configure the suite uses.
        Any kwarg we don't understand falls through to tk.Label."""
        if cnf is not None and not kw:
            return super().configure(cnf)
        passthrough = {}
        for k, v in kw.items():
            if k == "text":
                self._text = v
                super().configure(text=v)
                self._refresh_image()
            elif k == "bg" or k == "background":
                self._bg = v
                # Only repaint to the new bg when we're not currently
                # hovered — otherwise the new bg takes effect on leave.
                if self._current_bg != self._hover_bg:
                    self._current_bg = v
                    self._set_image_for_bg(v)
            elif k == "fg" or k == "foreground":
                self._fg = v
                super().configure(fg=v)
            elif k == "font":
                self._font = v
                super().configure(font=v)
                self._refresh_image()
            elif k == "state":
                self._state = v
                if v == "disabled":
                    self._apply_disabled_style()
                else:
                    try:
                        tk.Label.configure(self, cursor="hand2",
                                            foreground=self._fg)
                    except Exception:
                        pass
            elif k == "command":
                self._command = v or (lambda: None)
            elif k == "image":
                # Caller is doing something exotic — they win, we drop
                # the rounded backdrop AND mark `_external_image` so
                # future hover tweens don't repaint the image (which
                # would make the caller's icon disappear on every
                # mouse-enter; root cause of the broken Trello hover).
                self._current_image = None
                self._external_image = True
                super().configure(image=v, compound="center")
            else:
                passthrough[k] = v
        if passthrough:
            super().configure(**passthrough)

    config = configure

    def cget(self, key):
        if key == "text":           return self._text
        if key in ("bg", "background"):  return self._bg
        if key in ("fg", "foreground"):  return self._fg
        if key == "state":          return self._state
        if key == "font":           return self._font
        if key == "command":        return self._command
        return super().cget(key)

    def invoke(self):
        """tk.Button.invoke compat — call the command directly."""
        if self._state != "disabled":
            try:
                self._command()
            except Exception:
                pass


# ── Factory entrypoints ─────────────────────────────────────────────────────

def _maybe_tip(widget, tooltip):
    """Attach a hover tooltip to `widget` when `tooltip` is provided.
    Centralised so every factory below picks up the same behaviour
    without a tk import dance — tool_panel.attach_tooltip handles the
    actual Toplevel lifecycle."""
    if tooltip:
        try:
            from tool_panel import attach_tooltip
            attach_tooltip(widget, tooltip)
        except Exception:
            pass
    return widget


def _make(parent, text, *, bg, fg, hover_bg, hover_fg=None,
           padx, pady, font, radius, command, tooltip):
    btn = RoundedButton(
        parent, text=text,
        bg=bg, fg=fg, hover_bg=hover_bg, hover_fg=hover_fg,
        font=font, padx=padx, pady=pady, radius=radius,
        command=command)
    return _maybe_tip(btn, tooltip)


def done_button(parent, text, *, command=None,
                 padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                 font=_DEFAULT_FONT_BOLD, tooltip=None):
    """Primary success action — green-tinted, bold. Use for:
    "✓ Done", "✓ Resolved", "✓ Completed", "Done in XA"."""
    return _make(parent, text,
                  bg=SUCCESS_BG, fg=SUCCESS_FG, hover_bg=SUCCESS_HOVER,
                  padx=padx, pady=pady, font=font, radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def send_button(parent, text, *, command=None,
                 padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                 font=_DEFAULT_FONT_BOLD, tooltip=None):
    """Primary informational action — blue-tinted, bold. Use for:
    "📋 Send 48h ack", "📋 Send weekly note", "📋 Copy & send"."""
    return _make(parent, text,
                  bg=INFO_BG, fg=INFO_FG, hover_bg=INFO_HOVER,
                  padx=padx, pady=pady, font=font, radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def link_button(parent, text, *, command=None,
                 padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                 font=_DEFAULT_FONT_BOLD, tooltip=None):
    """Secondary informational link — paler blue, bold. Use for:
    "📨 Open email", "📁 OD", "📂 Make folders" — anything that's a
    "jump to another surface" affordance, distinct from a primary
    action that drives the row's workflow."""
    return _make(parent, text,
                  bg=LINK_BG, fg=LINK_FG, hover_bg=LINK_HOVER,
                  padx=padx, pady=pady, font=font, radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def secondary_button(parent, text, *, command=None,
                      padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                      font=_DEFAULT_FONT, tooltip=None):
    """Quiet action — softer surface tint. Use for: "Snooze 1d",
    "⏭ Skip", "Dismiss", "📋 Copy note", "Cancel"."""
    return _make(parent, text,
                  bg=SURFACE_2, fg=TEXT_DARK, hover_bg=NEUTRAL_HOVER,
                  padx=padx, pady=pady, font=font, radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def warn_button(parent, text, *, command=None,
                 padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                 font=_DEFAULT_FONT_BOLD, tooltip=None):
    """Caution-level action — amber-tinted. Use for: "⏱ Extend"
    (non-overdue), heads-up actions that aren't urgent enough for
    danger styling."""
    return _make(parent, text,
                  bg=WARN_BG, fg=WARN_FG, hover_bg=WARN_HOVER,
                  padx=padx, pady=pady, font=font, radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def danger_button(parent, text, *, command=None,
                   padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                   font=_DEFAULT_FONT_BOLD, tooltip=None):
    """Urgent / destructive action — red-tinted. Use for: "⏱ Extend"
    when overdue, "Force delete", or any irreversible action that
    needs to draw the eye."""
    return _make(parent, text,
                  bg=DANGER_BG, fg=DANGER_FG, hover_bg=DANGER_HOVER,
                  padx=padx, pady=pady, font=font, radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def icon_button(parent, icon, *, command=None, fg=TEXT_GRAY,
                 hover=NEUTRAL_HOVER, padx=6, pady=4,
                 font=(FONT_FAMILY, 10), bg=WHITE, tooltip=None):
    """Tiny flat icon button — for 🗑 dismiss / 📁 open / ✏ edit /
    × close. Defaults to muted gray fg so it sits quiet next to a
    primary action button. Pass `fg=DANGER_FG` for destructive
    icons, `fg=LINK_FG` for navigation icons, etc."""
    return _make(parent, icon,
                  bg=bg, fg=fg, hover_bg=hover,
                  padx=padx, pady=pady, font=font,
                  radius=_DEFAULT_RADIUS,
                  command=command, tooltip=tooltip)


def trello_link_button(parent, *, command=None, padx=8, pady=4,
                         tooltip="Open Trello card",
                         client=None, on_pinned=None, pinned=None):
    """Tiny "open Trello card" button — Trello logo image when the
    icon asset is available, falls back to a bold blue "T" character
    when the PNG can't be loaded (e.g. when the deploy bundle skipped
    `trello.png`). Identical visual everywhere it's used so the
    "where do I click to jump to Trello?" answer is always the same
    shape and color across every panel.

    Does NOT route through `RoundedButton` because the rounded
    backdrop's hover-tween regenerates the `image=` attribute every
    frame — which would overwrite the Trello PNG and make the button
    visibly disappear on hover. The icon-only Trello variant uses a
    plain `tk.Label` with bindings instead, getting the same hover
    feedback via `attach_hover_tween` on the Label's background.

    Right-click menu (when `client` is provided): mirrors the OD-folder
    pattern from job_widgets — "📌 Pin Trello card…" when no card is
    pinned, "📌 Change pinned card…" when one is. Calls the existing
    `job_widgets.open_trello_pin_dialog`. `on_pinned(card_ids)` fires
    after the user saves the dialog so callers can refresh the row.
    `pinned` overrides the auto-detected pin state (pass False to force
    "Pin…" wording on a button you know has no card; pass True to force
    "Change…"); leave None to auto-detect from persistence.
    """
    try:
        from trello_icon import trello_icon as _trello_icon
        ico = _trello_icon(parent)
    except Exception:
        ico = None
    try:
        raw_bg = parent.cget("bg")
        # Resolve Tk-named colors ("SystemButtonFace") to actual hex
        # so the hover tween's color math doesn't see opaque names.
        if raw_bg and not raw_bg.startswith("#"):
            r, g, b = parent.winfo_rgb(raw_bg)
            parent_bg = f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"
        else:
            parent_bg = raw_bg or WHITE
    except Exception:
        parent_bg = WHITE
    if ico is not None:
        btn = tk.Label(parent, image=ico, bg=parent_bg, bd=0,
                        highlightthickness=0, cursor="hand2",
                        padx=padx, pady=pady)
        btn._trello_icon_ref = ico  # GC guard
    else:
        btn = tk.Label(parent, text="T", bg=parent_bg, fg=LINK_FG,
                        font=(FONT_FAMILY, 9, "bold"),
                        bd=0, highlightthickness=0, cursor="hand2",
                        padx=padx, pady=pady)
    # Hover tween — pulse the Label's bg between parent_bg and a
    # subtle neutral hover. The image stays untouched, so the icon
    # doesn't disappear mid-hover the way it did when this routed
    # through RoundedButton.
    try:
        from theme import attach_hover_tween
        attach_hover_tween(btn, parent_bg, NEUTRAL_HOVER)
    except Exception:
        pass
    if command is not None:
        btn.bind("<Button-1>", lambda _e=None: command())
    if client:
        _attach_trello_pin_menu(btn, client,
                                 on_pinned=on_pinned, pinned=pinned)
    return _maybe_tip(btn, tooltip)


def _attach_trello_pin_menu(widget, client, *, on_pinned=None,
                              pinned=None):
    """Bind <Button-3> on `widget` to a tiny popup menu that opens the
    shared Trello pin dialog. Lazy-imports persistence + job_widgets so
    we don't add load-time cycles to ui_buttons (which is imported by
    nearly every panel)."""
    def _has_pin():
        if pinned is not None:
            return bool(pinned)
        try:
            import persistence as _per
            cid = _per.get_trello_card_id(client) or ""
            return bool(cid)
        except Exception:
            return False

    def _open_pin_dialog(_e=None):
        try:
            import job_widgets as _jw
        except Exception:
            return
        host = widget.winfo_toplevel()
        try:
            _jw.open_trello_pin_dialog(host, client,
                                         on_pinned=on_pinned)
        except TypeError:
            try:
                _jw.open_trello_pin_dialog(host, client)
            except Exception:
                pass
        except Exception:
            pass

    def _popup(event):
        menu = tk.Menu(widget, tearoff=0)
        label = ("📌 Change pinned card…" if _has_pin()
                  else "📌 Pin Trello card…")
        menu.add_command(label=label, command=_open_pin_dialog)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except Exception: pass

    widget.bind("<Button-3>", _popup)


def chip_label(parent, text, *, kind="info",
                font=(FONT_FAMILY, 9, "bold"),
                padx=10, pady=3, tooltip=None):
    """Pill-shaped status label — same kind taxonomy as buttons but
    non-interactive. Use for the urgent/warn/ok chips that appear at
    the head of Hygiene rows, audit cards, and snapshot lanes.

    Rendered through RoundedButton too so the chip silhouette matches
    the action buttons; the click handler is a no-op.

    `kind` ∈ {"danger", "warn", "ok", "info", "link", "muted"}.
    """
    palette = {
        "danger":  (DANGER_HOVER,  FLAG_RED),
        "warn":    (WARN_HOVER,    WARN_FG),
        "ok":      (SUCCESS_HOVER, SUCCESS_FG),
        "info":    (INFO_HOVER,    INFO_FG),
        "link":    (LINK_HOVER,    LINK_FG),
        "muted":   (SURFACE_2,     TEXT_GRAY),
    }
    bg, fg = palette.get(kind, palette["info"])
    btn = RoundedButton(
        parent, text=text, bg=bg, fg=fg, hover_bg=bg,
        font=font, padx=padx, pady=pady,
        radius=_DEFAULT_RADIUS, command=None, state="disabled")
    # Chips are visual-only — neutralize hover & press by leaving them
    # in the "disabled" state from creation.
    btn._on_enter = lambda _e=None: None
    btn._on_leave = lambda _e=None: None
    btn._on_press = lambda _e=None: None
    btn._on_release = lambda _e=None: None
    btn.configure(cursor="arrow")
    return _maybe_tip(btn, tooltip)


def status_button(parent, text, *, kind="info", command=None,
                   padx=_DEFAULT_PADX, pady=_DEFAULT_PADY,
                   font=_DEFAULT_FONT_BOLD,
                   tooltip=None):
    """Status-aware factory — picks the visual kind by name. Useful
    when a button's severity is driven by row state (e.g., Extend is
    `warn` normally but `danger` once the SLA is past).

    `kind` ∈ {"info", "done", "warn", "danger", "link", "secondary"}.
    """
    table = {
        "info":      send_button,
        "done":      done_button,
        "warn":      warn_button,
        "danger":    danger_button,
        "link":      link_button,
        "secondary": secondary_button,
    }
    fn = table.get(kind, send_button)
    return fn(parent, text, command=command, padx=padx, pady=pady,
              font=font, tooltip=tooltip)
