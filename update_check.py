"""Transition updater: public version metadata, private browser downloads.

Main selects the newest valid oneloss.work or GitHub feed. Trial
continues to use GitHub. No Access service secret belongs in a desktop build.
"""
from __future__ import annotations
import json
import re
import urllib.request
import paths

_CHANNEL = "trial" if getattr(paths, "IS_TRIAL", False) else "main"
RAW_URL = f"https://raw.githubusercontent.com/ManTreeJoe/linguar-hub-releases/main/{_CHANNEL}/version.txt"
TEAM_URL = "https://updates.oneloss.work/main/version.txt"


def _tuple(value):
    return tuple(int(x) for x in re.findall(r"\d+", value or "0")) or (0,)


def check(timeout=6.0):
    current = str(getattr(paths, "VERSION", "0")).strip()
    sources = [RAW_URL] if _CHANNEL == "trial" else [TEAM_URL, RAW_URL]
    candidates = []
    for source in sources:
        try:
            request = urllib.request.Request(source, headers={"User-Agent": "OneLoss-Updates"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                # A protected metadata path must not become an HTML login page.
                data = json.loads(response.read(128 * 1024).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid feed")
            latest = str(data.get("version") or "").strip()
            if latest and not re.fullmatch(r"\d+(?:\.\d+)+(?:[-.][A-Za-z0-9.]+)?", latest):
                raise ValueError("Invalid version")
            private = source == TEAM_URL
            installer = str(data.get("installer") or "")
            page = str(data.get("url") or "")
            if private:
                if not latest:
                    raise ValueError("Missing private version")
                if not re.fullmatch(r"https://updates\.oneloss\.work/downloads/[A-Za-z0-9][A-Za-z0-9._-]*\.exe", installer):
                    raise ValueError("Invalid private download")
                if page not in ("https://updates.oneloss.work", "https://updates.oneloss.work/"):
                    raise ValueError("Invalid release page")
                if not re.fullmatch(r"[a-fA-F0-9]{64}", str(data.get("sha256") or "")):
                    raise ValueError("Missing release checksum")
            else:
                # Preserve the legacy GitHub channel, but reject executable
                # URLs outside its exact release repository.
                if installer and not installer.startswith("https://github.com/ManTreeJoe/linguar-hub-releases/releases/download/"):
                    raise ValueError("Invalid legacy installer")
                if not page.startswith("https://github.com/ManTreeJoe/linguar-hub-releases/releases/"):
                    raise ValueError("Invalid legacy release page")
            checksum = str(data.get("sha256") or "")
            if checksum and not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
                raise ValueError("Invalid checksum")
            candidates.append({"ok": True, "update_available": _tuple(latest) > _tuple(current),
                    "current": current, "latest": latest, "url": page,
                    "installer": installer, "notes": str(data.get("notes") or ""),
                    "private_download": private, "source": source,
                    "sha256": checksum})
        except Exception:
            continue
    if candidates:
        # Stable max keeps the private feed on equal versions only.
        return max(candidates, key=lambda item: _tuple(item["latest"]))
    return {"ok": False, "error": "Update feeds unavailable", "current": current,
            "update_available": False}
