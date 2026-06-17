"""DPI awareness + scaling for the EMS Tools suite.

Why this exists:
    Tk on Windows is NOT DPI-aware by default. On a 4K laptop with
    200% display scaling, Windows lies to the app (reports the screen
    as 1920×1080 @ 96 DPI) and then bitmap-upscales the rendered
    window — net effect: the app looks blurry AND tiny because Tk
    sized everything for a non-scaled 1080p display.

    Fixing both halves:
      1. `enable_dpi_awareness()` — Win32 SetProcess*DpiAware* so the
         OS stops lying and gives us the real pixel dimensions. Must
         be called BEFORE any Tk window exists (at module-import
         time of the launcher / a standalone tool's `main`).
      2. `apply_window_scaling(root)` — reads the real DPI from a
         live Tk root and applies a matching scale factor to Tk's
         widget metrics (`tk.scaling`) and CustomTkinter
         (`set_widget_scaling` / `set_window_scaling`). End result:
         widgets stay PHYSICALLY the same size whether the user is
         on a 4K laptop @ 200% or a 27" monitor @ 100%.

Best-effort: every call is wrapped — older Windows / missing
customtkinter / Tk-only deploys all degrade silently to the 1.0
baseline, which is the prior behavior.
"""
from __future__ import annotations

import ctypes


def enable_dpi_awareness() -> None:
    """Tell Windows the process is DPI-aware so it stops bitmap-
    scaling the window. Must be called BEFORE any Tk window exists.

    Tries the most-precise mode first and falls back through legacy
    APIs for compatibility with older Windows versions.
    """
    try:
        # Per-Monitor V2 (Windows 10 1703+) — best fidelity, lets the
        # app react to monitor moves with WM_DPICHANGED. Constant is
        # -4 cast as void pointer.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        # System Aware (Windows 8.1+) — DPI fixed at process start
        # based on the primary monitor.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except (AttributeError, OSError):
        pass
    try:
        # Legacy DPI Aware (Vista+).
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_USER_SCALE_KEY = "ui_scale"


def _user_scale_override():
    """Read the user-set scale override from config.json. Returns the
    float value when set + valid, or None to fall through to auto-
    detection. Lets the user pin a specific size when the auto-
    detected DPI is wrong for their setup (4K laptop at OS 100%, an
    external monitor with a quirky EDID, etc.).

    Source is config.json (the Settings dialog edits) — NOT
    persistence/state.json. Settings dialog → config.save → next
    process start picks it up via this path."""
    try:
        import config as _cfg
        raw = _cfg.load().get(_USER_SCALE_KEY)
    except Exception:
        return None
    if raw is None or raw == "" or str(raw).lower() == "auto":
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.75, min(3.0, val))


_BASELINE_MIN_SCALE = 1.30   # default baseline when no DPI signal


def _detected_scale(root) -> float:
    """Compute the scale factor for `root`'s current monitor.

    Priority:
      1. Persistent user override (`ui_scale` in config.json) — wins
         when set. Use Settings → UI scale (or Ctrl+= / Ctrl+-) to
         dial it in.
      2. Reported screen DPI ÷ 96 (the standard Windows baseline) —
         on screens where Windows actually reports a custom DPI
         (anything past 100% display scaling), we honor it.
      3. Wide-screen fallback — when a screen reads as 2560+ wide
         after DPI awareness is enabled, the OS is probably at 100%
         scaling on a high-density panel; bump anyway.
      4. **Baseline minimum** — when nothing above triggered, default
         to ``_BASELINE_MIN_SCALE`` (1.30) instead of 1.0. This is
         what makes the app "laptop friendly by default" — 14"
         1920×1080 laptops have small pixels even though Windows
         reports 96 DPI, and the prior 1.0 default rendered the app
         too small to read. 27"+ monitor users can Ctrl+- once to
         dial back to 1.0 if 1.30 feels chunky.

    Clamped to [0.75, 3.0].
    """
    # 1. Persistent override
    user_override = _user_scale_override()
    if user_override is not None:
        return user_override
    # 2. DPI-based detection
    try:
        root.update_idletasks()
        dpi = root.winfo_fpixels("1i")
    except Exception:
        dpi = 96.0
    scale = dpi / 96.0
    # 3. Wide-screen fallback for the OS-100%-on-high-density-panel case
    if scale <= 1.0:
        try:
            w = root.winfo_screenwidth()
        except Exception:
            w = 0
        if w >= 3840:
            scale = 2.0
        elif w >= 2560:
            scale = 1.5
        else:
            # 4. Baseline minimum — see docstring. The "I just need
            # everything bigger by default" path for 1920×1080 14"
            # laptops where Tk has no DPI signal to work with.
            scale = _BASELINE_MIN_SCALE
    return min(3.0, max(0.75, scale))


def apply_window_scaling(root) -> float:
    """Apply DPI-matched scaling to `root` (a Tk / CTk window).

    Returns the scale factor used. Always applies the scale to both
    Tk and CTk (even at 1.0) — that way a re-call after a runtime
    override change reliably resets metrics.
    """
    scale = _detected_scale(root)
    _apply_scale_to(root, scale)
    return scale


def _apply_scale_to(root, scale):
    """Push `scale` into Tk + CTk. Split out so the keyboard-shortcut
    handler can re-apply at runtime without re-running detection."""
    try:
        root.tk.call("tk", "scaling", float(scale))
    except Exception:
        pass
    try:
        import customtkinter as _ctk
        _ctk.set_widget_scaling(float(scale))
        _ctk.set_window_scaling(float(scale))
    except Exception:
        pass


# Runtime keyboard-controlled scaling. Bound on the launcher (and
# every standalone tool root) so the user can dial in their preferred
# size live with Ctrl+= / Ctrl+- / Ctrl+0 — useful when bouncing
# between a 4K laptop and a 27" external monitor mid-session.
_SCALE_STEP_DEFAULT = 0.1
_SCALE_MIN = 0.75
_SCALE_MAX = 3.0


def _current_scale(root):
    """Best read of the scale Tk currently believes is in use."""
    try:
        return float(root.tk.call("tk", "scaling"))
    except Exception:
        return 1.0


def _persist_scale(value):
    """Update config.json so the new scale survives a restart. Wraps
    config.load / save so we don't clobber unrelated settings."""
    try:
        import config as _cfg
        cfg = _cfg.load()
        cfg[_USER_SCALE_KEY] = round(float(value), 2)
        _cfg.save(cfg)
    except Exception:
        pass


_SCALER_INSTALLED = [False]
_SCALER_FACTOR = [1.0]


def _scale_font_arg(value, factor):
    """Multiply the point size in a font tuple / string. Negative
    sizes (Tk's pixel-size convention) are also scaled. Returns the
    new font spec, leaving the family + style untouched."""
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        family = value[0]
        size = value[1]
        if isinstance(size, (int, float)):
            sign = -1 if size < 0 else 1
            new_size = max(1, int(round(abs(size) * factor))) * sign
            return (family, new_size) + tuple(value[2:])
    return value


def _scale_pad_arg(value, factor):
    """Scale a padx/pady value. Accepts ints, floats, or (top,bot)
    tuples. Returns scaled equivalent."""
    if isinstance(value, (int, float)):
        return max(0, int(round(value * factor)))
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return (max(0, int(round(value[0] * factor))),
                max(0, int(round(value[1] * factor))))
    return value


def install_widget_scaler(scale):
    """Monkey-patch tkinter so EVERY widget created from this point on
    gets its font size + padx/pady multiplied by `scale`. This is the
    bit that actually makes elements (not just fonts, not just the
    window) bigger — Tk's built-in tk.scaling only affects positive-
    point font sizes, leaving widget paddings and pixel-spec'd fonts
    untouched, which is why widgets stayed visually the same while
    only the chrome grew.

    Idempotent: safe to call repeatedly, but only the FIRST call's
    factor sticks. Re-running with a different factor would compound
    the effect on widgets created between calls — to change factor,
    restart the process. Caller is expected to set this before any
    panels are built.
    """
    if _SCALER_INSTALLED[0]:
        return
    if scale is None or abs(float(scale) - 1.0) < 0.01:
        return  # no-op at 1.0

    import tkinter as _tk
    _SCALER_FACTOR[0] = float(scale)

    # Save the originals — Pack / Grid are mixin classes that hold
    # `pack_configure` / `grid_configure`. tk.Widget inherits both,
    # so patching the mixins covers every widget class.
    orig_basewidget = _tk.BaseWidget.__init__
    orig_pack = _tk.Pack.pack_configure
    orig_grid = _tk.Grid.grid_configure

    def _scaled_basewidget(self, master, widgetName, cnf=None, kw=None,
                            extra=()):
        # Tk's BaseWidget accepts cnf as positional dict + kw as **kw.
        # Normalize both, scale, and pass through. The signature varies
        # slightly between Tk versions — we accept either calling form.
        if cnf is None:
            cnf = {}
        if kw is None:
            kw = {}
        f = _SCALER_FACTOR[0]
        # Scale font + padding in both option dicts.
        for d in (cnf, kw):
            if not isinstance(d, dict):
                continue
            if "font" in d:
                d["font"] = _scale_font_arg(d["font"], f)
            for k in ("padx", "pady", "ipadx", "ipady"):
                if k in d:
                    d[k] = _scale_pad_arg(d[k], f)
        return orig_basewidget(self, master, widgetName, cnf, kw, extra)

    def _scaled_pack(self, cnf={}, **kw):
        f = _SCALER_FACTOR[0]
        if isinstance(cnf, dict):
            cnf = dict(cnf)
            for k in ("padx", "pady", "ipadx", "ipady"):
                if k in cnf:
                    cnf[k] = _scale_pad_arg(cnf[k], f)
        for k in ("padx", "pady", "ipadx", "ipady"):
            if k in kw:
                kw[k] = _scale_pad_arg(kw[k], f)
        return orig_pack(self, cnf, **kw)

    def _scaled_grid(self, cnf={}, **kw):
        f = _SCALER_FACTOR[0]
        if isinstance(cnf, dict):
            cnf = dict(cnf)
            for k in ("padx", "pady", "ipadx", "ipady"):
                if k in cnf:
                    cnf[k] = _scale_pad_arg(cnf[k], f)
        for k in ("padx", "pady", "ipadx", "ipady"):
            if k in kw:
                kw[k] = _scale_pad_arg(kw[k], f)
        return orig_grid(self, cnf, **kw)

    _tk.BaseWidget.__init__ = _scaled_basewidget
    _tk.Pack.pack_configure = _scaled_pack
    _tk.Pack.pack = _scaled_pack
    _tk.Grid.grid_configure = _scaled_grid
    _tk.Grid.grid = _scaled_grid
    _SCALER_INSTALLED[0] = True


def rescale_live(root, new_scale):
    """Live-rescale every already-rendered widget under `root`.

    Walks the widget tree from the root down. For each widget, reads
    its current font + padx/pady, multiplies by the ratio
    ``new_scale / current_scale``, and re-applies. Updates the
    global `_SCALER_FACTOR` so future widgets (e.g. dialogs spawned
    later) get sized at the new scale via the monkey-patch.

    This is the path that actually changes element sizes WITHOUT
    closing the app. Tk's tk.scaling alone won't do it — widgets
    keep their original baked-in dimensions until reconfigured.

    Drift note: each call multiplies by a ratio, so chained Ctrl+=
    presses accumulate floating-point error. After ~20 presses the
    drift is still well under 1px; for normal use (dial in 3-5
    presses, settle) it's invisible.
    """
    import tkinter as _tk
    cur = _SCALER_FACTOR[0] or 1.0
    new = max(_SCALE_MIN, min(_SCALE_MAX, float(new_scale)))
    ratio = new / cur if cur else new
    if abs(ratio - 1.0) < 0.005:
        return  # within rounding — skip the walk

    def _rescale_font(widget):
        # Read the widget's current font and parse out the size.
        # cget returns either a font name (TkDefaultFont, etc.) or a
        # tuple-format string ("{Segoe UI Variable} 12 bold").
        try:
            raw = widget.cget("font")
        except (_tk.TclError, AttributeError):
            return
        if not raw:
            return
        try:
            import tkinter.font as _tkfont
            f = _tkfont.Font(root=widget.master or widget, font=raw)
            cur_size = int(f.actual("size") or 0)
        except Exception:
            return
        if cur_size == 0:
            return
        # Positive size = points, negative = pixels. Both scale.
        sign = -1 if cur_size < 0 else 1
        new_size = max(1, int(round(abs(cur_size) * ratio))) * sign
        if new_size == cur_size:
            return
        try:
            family  = f.actual("family") or "Segoe UI Variable"
            weight  = f.actual("weight")  or "normal"
            slant   = f.actual("slant")   or "roman"
            new_font = (family, new_size,
                        "bold"  if weight == "bold"  else "normal",
                        "italic" if slant  == "italic" else "roman")
            # Trim trailing 'normal'/'roman' for cleanliness.
            while new_font and new_font[-1] in ("normal", "roman"):
                new_font = new_font[:-1]
            widget.configure(font=new_font)
        except _tk.TclError:
            pass

    def _rescale_pads(widget):
        for opt in ("padx", "pady", "ipadx", "ipady"):
            try:
                raw = widget.cget(opt)
            except (_tk.TclError, AttributeError):
                continue
            try:
                v = int(raw)
            except (TypeError, ValueError):
                continue
            if v <= 0:
                continue
            new_v = max(0, int(round(v * ratio)))
            if new_v == v:
                continue
            try:
                widget.configure(**{opt: new_v})
            except _tk.TclError:
                pass

    def _walk(widget):
        try:
            _rescale_font(widget)
        except Exception:
            pass
        try:
            _rescale_pads(widget)
        except Exception:
            pass
        # Also scale pack/grid info (per-call padding). The root Tk
        # object doesn't have pack_info — guard with hasattr + catch
        # AttributeError so we don't blow up on toplevels either.
        pack_info_fn = getattr(widget, "pack_info", None)
        if callable(pack_info_fn):
            try:
                info = pack_info_fn()
            except (_tk.TclError, AttributeError):
                info = None
            if info:
                for opt in ("padx", "pady", "ipadx", "ipady"):
                    if opt not in info:
                        continue
                    try:
                        v = int(info[opt])
                    except (TypeError, ValueError):
                        continue
                    if v <= 0:
                        continue
                    new_v = max(0, int(round(v * ratio)))
                    if new_v != v:
                        try:
                            widget.pack_configure(**{opt: new_v})
                        except (_tk.TclError, AttributeError):
                            pass
        try:
            for child in widget.winfo_children():
                _walk(child)
        except _tk.TclError:
            pass

    _walk(root)
    _SCALER_FACTOR[0] = new
    # Also update tk.scaling + ctk scaling so future widgets pick up.
    _apply_scale_to(root, new)


def _restart_app():
    """Re-spawn the current process with the same argv and exit.

    Tk's runtime ``tk.scaling`` change only updates NEWLY-laid-out
    widgets — every already-on-screen Label/Button/Frame keeps its
    pre-change size. Restarting is the only reliable way to render
    every widget at the new scale.

    Works for both python.exe + script and the PyInstaller bundle
    (sys.executable resolves to the right binary in each case).
    """
    import sys
    import subprocess
    try:
        # Spawn the replacement process detached so closing the old
        # process doesn't kill the new one.
        if getattr(sys, "frozen", False):
            # PyInstaller bundle: re-exec the exe itself.
            subprocess.Popen([sys.executable] + sys.argv[1:],
                             close_fds=True)
        else:
            subprocess.Popen([sys.executable] + sys.argv,
                             close_fds=True)
    except Exception:
        return
    # Best-effort tear-down + exit. os._exit dodges atexit hooks that
    # might try to access already-destroyed Tk widgets.
    import os
    try:
        os._exit(0)
    except Exception:
        sys.exit(0)


def bind_scale_shortcuts(root, *, step=_SCALE_STEP_DEFAULT,
                           on_change=None):
    """Wire Ctrl+= / Ctrl++ / Ctrl+- / Ctrl+0 on `root`. Each press:
      1. Live-rescales every widget under `root` via `rescale_live`
         (walks the tree + multiplies fonts + paddings in place).
      2. Persists the new value to config.json so next launch starts
         at the same scale.
      3. Fires `on_change(scale)` for the caller's toast / status.

    The live walk means the user sees the change IMMEDIATELY — no
    close-and-reopen required. Drift accumulates slightly with each
    press (ratio-based), but settling on a value after a few taps
    is well within rounding tolerance.
    """
    if root is None:
        return

    def _adjust(delta):
        cur_v = _SCALER_FACTOR[0] or 1.0
        new = max(_SCALE_MIN, min(_SCALE_MAX, float(cur_v) + delta))
        try:
            rescale_live(root, new)
        except Exception:
            pass
        _persist_scale(new)
        if on_change is not None:
            try:
                on_change(new)
            except Exception:
                pass

    def _reset():
        try:
            rescale_live(root, 1.0)
        except Exception:
            pass
        _persist_scale(1.0)
        if on_change is not None:
            try:
                on_change(1.0)
            except Exception:
                pass

    for seq in ("<Control-equal>", "<Control-plus>",
                "<Control-KP_Add>"):
        try:
            root.bind_all(seq, lambda _e, d=step: _adjust(d))
        except Exception:
            pass
    for seq in ("<Control-minus>", "<Control-KP_Subtract>"):
        try:
            root.bind_all(seq, lambda _e, d=step: _adjust(-d))
        except Exception:
            pass
    for seq in ("<Control-Key-0>", "<Control-KP_0>"):
        try:
            root.bind_all(seq, lambda _e: _reset())
        except Exception:
            pass
