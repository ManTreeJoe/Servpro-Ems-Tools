"""Per-department browser routing.

IE and OC can open their web links (Trello / XactAnalysis / CompanyCam) in
DIFFERENT browsers — e.g. two separate Helium installs, or the same browser
with different --profile-directory args — so the two departments' logins stay
separate. Configured in Settings; falls back to the system default browser
when a department has no browser set.

Config shape (in config.json, per-department is fine but the value is global):
    "dept_browsers": { "IE": "<exe or command>", "OC": "<exe or command>" }

The value is either:
  • a path to a browser .exe  → launched as `<exe> <url>`, or
  • a command template containing `{url}` → shell-split and substituted,
    e.g.  `C:\\Helium\\helium.exe --profile-directory=OC {url}`
"""
from __future__ import annotations
import os
import shlex
import subprocess
import webbrowser

import config


def _dept_command() -> str:
    """The configured browser command for the ACTIVE department, or ''."""
    try:
        dept = (config.active_department() or "").strip().upper()
        browsers = (config.load() or {}).get("dept_browsers") or {}
        # Accept case-variant keys ("ie"/"IE").
        for k, v in browsers.items():
            if (k or "").strip().upper() == dept and (v or "").strip():
                return v.strip()
    except Exception:
        pass
    return ""


def open_url(url: str) -> bool:
    """Open `url` in the active department's browser, else the default."""
    if not url:
        return False
    cmd = _dept_command()
    if cmd:
        try:
            if "{url}" in cmd:
                parts = [p.replace("{url}", url) for p in shlex.split(cmd, posix=False)]
            else:
                # Bare exe path (may contain spaces) + the url as an argument.
                exe = cmd.strip('"')
                parts = [exe, url]
            # Validate the executable exists when it's a plain path.
            if len(parts) == 1 or os.path.isfile(parts[0].strip('"')) or "{url}" in cmd:
                subprocess.Popen(parts, close_fds=True)
                return True
        except Exception:
            pass   # fall through to default
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False
