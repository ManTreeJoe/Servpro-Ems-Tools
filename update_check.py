"""Lightweight update check.

The app polls a `version.txt` on the GitHub repo's main branch (raw). When its
`version` is newer than the running build's `paths.VERSION`, the launcher shows
an 'update available' banner linking to the download. No GitHub token / releases
API needed — bumping version.txt in the repo notifies everyone on the next
launch.

To ship an update: build the new exe, bump `paths.VERSION`, bump `version`
in version.txt (+ upload the zip to a GitHub Release), commit + push.
"""
from __future__ import annotations
import json
import re
import urllib.request

import paths

RAW_URL = ("https://raw.githubusercontent.com/ManTreeJoe/"
           "Servpro-Ems-Tools/main/version.txt")


def _tuple(v: str):
    """Version string → comparable tuple of ints ('1.10.0' → (1,10,0))."""
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")) or (0,)


def check(timeout: float = 6.0) -> dict:
    """Return {ok, update_available, current, latest, url, notes} — best
    effort; never raises."""
    current = str(getattr(paths, "VERSION", "0")).strip()
    try:
        req = urllib.request.Request(RAW_URL, headers={"User-Agent": "EMS-Tools"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = str(data.get("version") or "").strip()
        return {
            "ok": True,
            "update_available": bool(latest and _tuple(latest) > _tuple(current)),
            "current": current,
            "latest": latest,
            "url": data.get("url") or "",
            "installer": data.get("installer") or "",
            "notes": data.get("notes") or "",
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "current": current,
                "update_available": False}
