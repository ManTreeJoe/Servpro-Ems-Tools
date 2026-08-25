"""Optional Windows-wide shortcut that raises the existing Hub window."""
from __future__ import annotations

import os
import threading


SHORTCUTS = {
    "ctrl+alt+space": (0x0002 | 0x0001, 0x20),
    "ctrl+shift+space": (0x0002 | 0x0004, 0x20),
    "alt+shift+space": (0x0001 | 0x0004, 0x20),
    "ctrl+alt+h": (0x0002 | 0x0001, ord("H")),
}
LABELS = {
    "ctrl+alt+space": "Ctrl + Alt + Space",
    "ctrl+shift+space": "Ctrl + Shift + Space",
    "alt+shift+space": "Alt + Shift + Space",
    "ctrl+alt+h": "Ctrl + Alt + H",
}


def normalize(value):
    return str(value or "ctrl+alt+space").strip().lower().replace(" ", "")


class Manager:
    def __init__(self, callback):
        self.callback = callback
        self._thread = None
        self._thread_id = 0
        self._stop = threading.Event()
        self._status = {"supported": os.name == "nt", "enabled": False,
                        "registered": False, "shortcut": "ctrl+alt+space",
                        "label": LABELS["ctrl+alt+space"], "error": ""}

    def start(self):
        if os.name != "nt" or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run,
                                        name="linguar-global-hotkey", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread_id:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
            except Exception:
                pass

    def status(self):
        return dict(self._status)

    def _wanted(self):
        try:
            import config
            cfg = config.load_base() or {}
            return bool(cfg.get("global_hotkey_enabled")), normalize(
                cfg.get("global_hotkey"))
        except Exception:
            return False, "ctrl+alt+space"

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        # A timer keeps Settings changes live without restarting the app.
        user32.SetTimer(None, 1, 1500, None)
        registered_for = ""
        msg = wintypes.MSG()
        while not self._stop.is_set():
            enabled, shortcut = self._wanted()
            if shortcut not in SHORTCUTS:
                shortcut = "ctrl+alt+space"
            if registered_for and (not enabled or shortcut != registered_for):
                user32.UnregisterHotKey(None, 1)
                registered_for = ""
            if enabled and not registered_for:
                mods, key = SHORTCUTS[shortcut]
                ok = bool(user32.RegisterHotKey(None, 1, mods | 0x4000, key))
                if ok:
                    registered_for = shortcut
                self._status.update({
                    "enabled": True, "registered": ok, "shortcut": shortcut,
                    "label": LABELS[shortcut],
                    "error": "" if ok else "That shortcut is already used by another app.",
                })
            elif not enabled:
                self._status.update({"enabled": False, "registered": False,
                                     "shortcut": shortcut, "label": LABELS[shortcut],
                                     "error": ""})
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            if msg.message == 0x0312 and msg.wParam == 1:
                try:
                    self.callback()
                except Exception:
                    pass
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if registered_for:
            user32.UnregisterHotKey(None, 1)
        user32.KillTimer(None, 1)
