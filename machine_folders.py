"""Machine-local franchise folder topology behind one small interface."""
from __future__ import annotations

import datetime
import glob
import os
import re
from urllib.parse import unquote, urlparse


def local_path(value) -> str:
    raw = str(value or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    raw = os.path.expandvars(os.path.expanduser(unquote(raw)))
    if raw.lower().startswith("file:"):
        parsed = urlparse(raw.replace("\\", "/"))
        raw = (f"//{parsed.netloc}{parsed.path}" if parsed.netloc and
               parsed.netloc.lower() != "localhost" else parsed.path)
        if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
    return os.path.normpath(raw.replace("/", os.sep))


def rebase_user_path(value, home=None) -> str:
    """Translate C:\\Users\\someone\\... to this Windows profile."""
    path = local_path(value)
    if not path or os.path.exists(path):
        return path
    home = os.path.normpath(home or os.path.expanduser("~"))
    match = re.match(r"(?i)^[a-z]:\\users\\[^\\]+\\(.+)$", path)
    if match:
        candidate = os.path.join(home, match.group(1))
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
    return path


def derive_daily_run(job_root, configured="") -> str:
    configured = rebase_user_path(configured)
    if configured and os.path.isdir(configured):
        return configured
    root = rebase_user_path(job_root)
    if not root or not os.path.isdir(root):
        return configured
    year = str(datetime.date.today().year)
    names = ("Daily Run", "Daily Runs", "EMS Daily Run", "Run Docs")
    candidates = []
    for name in names:
        base = os.path.join(root, name)
        candidates.extend((os.path.join(base, year), base))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)
    for pattern in ("*Daily*Run*", "*Run*Doc*"):
        for candidate in glob.glob(os.path.join(root, pattern)):
            if os.path.isdir(os.path.join(candidate, year)):
                return os.path.normpath(os.path.join(candidate, year))
            if os.path.isdir(candidate):
                return os.path.normpath(candidate)
    return configured


def discover(department: str, profile: dict) -> dict:
    """Resolve and validate one franchise's roots on this machine."""
    job_root = rebase_user_path(profile.get("audit_base"))
    runs_dir = derive_daily_run(job_root, profile.get("runs_dir"))
    return {
        "key": str(department or "").strip().upper(),
        "label": profile.get("label") or department,
        "job_root": job_root,
        "runs_dir": runs_dir,
        "job_connected": bool(job_root and os.path.isdir(job_root)),
        "runs_connected": bool(runs_dir and os.path.isdir(runs_dir)),
    }


def connect(department: str, job_root: str, runs_dir: str = "") -> dict:
    """Validate a selected root and derive its Daily Run location."""
    result = discover(department, {"audit_base": job_root,
                                   "runs_dir": runs_dir})
    missing = []
    if not result["job_connected"]:
        missing.append("job folders root")
    if not result["runs_connected"]:
        missing.append("daily run docs folder")
    result["ok"] = not missing
    result["error"] = ("Windows cannot open the " + " and ".join(missing) + "."
                       if missing else "")
    return result

