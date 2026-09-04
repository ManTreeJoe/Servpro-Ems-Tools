"""Browser adapter for the existing Linguar Hub tool modules.

The desktop shell exposes :class:`home_web.HomeApi` to JavaScript through
pywebview.  Browser pages use the same interface through one HTTP endpoint.
Keeping that interface in one place means an existing tool can become browser
usable without growing a second set of Python methods or browser-specific
business logic.

Only public methods belonging to the shell or an explicitly registered tool
module are callable.  Native window attachment is never exposed.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
import threading
from typing import Any, Callable


# The shell methods are deliberately explicit.  Tool-prefixed methods are
# discovered only from the Api instances in HomeApi.SUB_MODULES, which is the
# same closed registry used by the desktop shell.
SHELL_METHODS = {
    "health_state", "appearance_preferences", "log_js_error", "track_events",
    "first_run", "preflight", "dismiss_first_run", "focus_window",
    "hotkey_status", "header", "active_work_environment",
    "work_environment_state", "switch_work_environment", "get_last_panel",
    "set_last_panel", "get_ui_state", "set_ui_state", "nav",
    "list_panel_visibility", "set_panel_visibility", "check_update",
    "open_url", "install_update", "counts", "get_starred_clients",
    "toggle_starred_client", "is_client_starred", "open_trello_for_client",
    "open_folder_for_client", "open_xa_for_client",
    "open_companycam_for_client", "trello_card_hover",
    "department_state", "switch_department",
}

# These methods control the Windows desktop rather than the browser.  They are
# useful when the portal is opened on the same PC, but must never make a remote
# browser operate the host computer.
HOST_ONLY_SHELL_METHODS = {
    "focus_window", "open_url", "install_update",
    "open_trello_for_client", "open_folder_for_client", "open_xa_for_client",
    "open_companycam_for_client", "switch_department",
}

# These actions do not merely control the host PC; their workflow only makes
# sense inside the packaged Windows shell.  A localhost browser is still a
# browser and must not be able to launch the desktop updater.
BROWSER_UNAVAILABLE_SHELL_METHODS = {"install_update"}


def _tool_method_controls_host(method: str) -> bool:
    """Identify methods whose result is a window/dialog on the portal PC."""
    return method.startswith((
        "open_", "reveal_", "pick_", "choose_", "teams_open_",
    )) or method in {
        "copy_to_clipboard", "set_clipboard", "copy_path",
        "relocate_workbook", "point_to_workbook", "change_audit_folder",
        "change_tracking_dir", "sp_browse_for_folder", "sp_open_folder",
        "navigate",
    }


def json_safe(value: Any) -> Any:
    """Return a JSON-compatible result without hiding ordinary structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


class BrowserWindowAdapter:
    """Supply the two native-window features existing panels depend on.

    Browser calls still run on the user's local portal process.  A standard
    Windows picker therefore remains possible even though there is no
    pywebview Window.  JavaScript progress pushes are intentionally a no-op;
    the HTTP call returns the final result and the existing progress UI still
    covers long actions client-side.
    """

    @staticmethod
    def _file_types(values) -> list[tuple[str, str]]:
        rows = []
        for value in values or ():
            text = str(value or "").strip()
            match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", text)
            if match:
                label = match.group(1).strip() or "Files"
                pattern = match.group(2).replace(";", " ")
                rows.append((label, pattern))
        return rows or [("All files", "*.*")]

    def create_file_dialog(self, dialog_type, directory="",
                           allow_multiple=False, file_types=(), **_kwargs):
        import tkinter as tk
        from tkinter import filedialog
        import webview

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            root.update_idletasks()
            options = {"parent": root}
            if directory:
                options["initialdir"] = directory
            if dialog_type == webview.FOLDER_DIALOG:
                value = filedialog.askdirectory(**options)
                return (value,) if value else None
            options["filetypes"] = self._file_types(file_types)
            if allow_multiple:
                values = filedialog.askopenfilenames(**options)
                return tuple(values) if values else None
            value = filedialog.askopenfilename(**options)
            return (value,) if value else None
        finally:
            root.destroy()

    @staticmethod
    def evaluate_js(_script):
        return None


class BrowserToolHost:
    """Expose the registered tool interface through a single browser seam."""

    def __init__(self, api_factory: Callable[[], Any] | None = None):
        self._api_factory = api_factory
        self._api = None
        self._allowed: set[str] = set()
        self._host_only: set[str] = set(HOST_ONLY_SHELL_METHODS)
        self._tool_methods: dict[str, set[str]] = {}
        self._init_lock = threading.Lock()

    def _ensure_api(self):
        if self._api is not None:
            return self._api
        with self._init_lock:
            if self._api is not None:
                return self._api
            if self._api_factory is None:
                from home_web import HomeApi
                api = HomeApi()
            else:
                api = self._api_factory()
            if callable(getattr(api, "attach", None)):
                api.attach(BrowserWindowAdapter())
            allowed = {
                name for name in SHELL_METHODS
                if callable(getattr(api, name, None))
            }
            tool_methods: dict[str, set[str]] = {}
            for tool, sub_api in dict(getattr(api, "_subs", {}) or {}).items():
                methods = {
                    name for name in dir(sub_api)
                    if not name.startswith("_")
                    and name != "attach"
                    and callable(getattr(sub_api, name, None))
                }
                tool_methods[str(tool)] = methods
                allowed.update(f"{tool}_{name}" for name in methods)
                self._host_only.update(
                    f"{tool}_{name}" for name in methods
                    if _tool_method_controls_host(name)
                )
            self._api = api
            self._allowed = allowed
            self._tool_methods = tool_methods
        return self._api

    def catalog(self) -> dict:
        api = self._ensure_api()
        failed = dict(getattr(api, "_failed_subs", {}) or {})
        return {
            "ok": True,
            "shell": "browser",
            "tools": [
                {
                    "key": key,
                    "available": key not in failed,
                    "methods": len(methods),
                    "error": failed.get(key, ""),
                }
                for key, methods in sorted(self._tool_methods.items())
            ],
        }

    def call(self, method: str, args: list | None = None,
             *, local_request: bool = True) -> Any:
        api = self._ensure_api()
        method = str(method or "").strip()
        if method in BROWSER_UNAVAILABLE_SHELL_METHODS:
            return {
                "ok": False,
                "error": "Install application updates from the Linguar Hub Windows app.",
                "desktop_only": True,
            }
        if not method or method.startswith("_") or method not in self._allowed:
            return {
                "ok": False,
                "error": "That browser tool action is not available.",
                "missing_method": True,
            }
        if not local_request and method in self._host_only:
            return {
                "ok": False,
                "error": "That action controls the Hub PC and is available only on that PC.",
                "local_only": True,
            }
        values = args if isinstance(args, list) else []
        try:
            return json_safe(getattr(api, method)(*values))
        except Exception as ex:
            return {
                "ok": False,
                "error": f"{type(ex).__name__}: {ex}",
                "method": method,
            }
