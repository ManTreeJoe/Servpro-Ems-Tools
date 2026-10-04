"""Token-free update checks against the public linguar-hub-releases repository.

Its main branch holds main/version.txt and trial/version.txt. Publishing a
verified installer updates the matching feed; newer builds show an update
banner on launch. The bundled version.txt identifies the running build.
"""
from __future__ import annotations
import json
import re
import urllib.request

import paths

# Both channel feeds live on the releases repository's main branch.
_CHANNEL = "trial" if getattr(paths, "IS_TRIAL", False) else "main"
RAW_URL = (f"https://raw.githubusercontent.com/ManTreeJoe/"
           f"linguar-hub-releases/main/{_CHANNEL}/version.txt")


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
