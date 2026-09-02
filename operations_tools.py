"""One launch interface for tools exposed by the Operations shell.

The browser and Windows shell are adapters at the same seam.  A tool key has
one meaning here; callers do not need to know panel names, legacy module
names, or the special New Loss hand-off into the mature intake workflow.
"""
from __future__ import annotations

from pathlib import Path


_TOOLS = {
    "new_job": {
        "label": "New loss",
        "browser_url": "/tools/?panel=daily_run&new_loss=1",
        "desktop_tool": "audit_web",
        "desktop_args": ("--new-loss",),
    },
    "audit_web": {"label": "Full Job Audit", "browser_url": "/tools/?panel=daily_run", "desktop_tool": "audit_web"},
    "run_doc_editor_web": {"label": "Edit Dispatch", "browser_url": "/tools/?panel=run_doc_editor", "desktop_tool": "run_doc_editor_web"},
    "snapshot_web": {"label": "Snapshot", "browser_url": "/tools/?panel=snapshot", "desktop_tool": "snapshot_web"},
    "job_notes_web": {"label": "Job Notes", "browser_url": "/tools/?panel=job_notes", "desktop_tool": "job_notes_web"},
    "apa_web": {"label": "APA", "browser_url": "/tools/?panel=apa", "desktop_tool": "apa_web"},
    "disputes_web": {"label": "Billing Disputes", "browser_url": "/tools/?panel=disputes", "desktop_tool": "disputes_web"},
    "kpi_web": {"label": "KPI", "browser_url": "/tools/?panel=kpi", "desktop_tool": "kpi_web"},
    "photo_folders_web": {"label": "Photo Folders", "browser_url": "/tools/?panel=photo_folders", "desktop_tool": "photo_folders_web"},
    "resources_web": {"label": "Forms & Resources", "browser_url": "/tools/?panel=resources", "desktop_tool": "resources_web"},
    "cheat_sheet_web": {"label": "Cheat Sheet", "browser_url": "/tools/?panel=cheat_sheet", "desktop_tool": "cheat_sheet_web"},
    "settings_web": {"label": "Settings", "browser_url": "/tools/?panel=settings", "desktop_tool": "settings_web"},
    "home_web": {"label": "All browser tools", "browser_url": "/tools/", "desktop_tool": "home_web"},
}


def catalog() -> dict:
    """Return JSON-safe metadata keyed by the stable Operations tool key."""
    return {
        key: {
            "label": item["label"],
            "browser_url": item["browser_url"],
            "desktop_tool": item["desktop_tool"],
        }
        for key, item in _TOOLS.items()
    }


def browser_routes() -> dict[str, str]:
    return {key: item["browser_url"] for key, item in _TOOLS.items()}


def launch_desktop(key: str, spawn=None) -> dict:
    """Launch a tool in Windows, including the real New Loss intake form."""
    item = _TOOLS.get(str(key or "").strip())
    if not item:
        return {"ok": False, "error": "That tool is not available here."}
    if spawn is None:
        from paths import spawn_tool
        spawn = spawn_tool
    try:
        spawn(item["desktop_tool"], *item.get("desktop_args", ()))
        return {"ok": True, "tool": key, "label": item["label"]}
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


def asset_health(root: str | Path) -> list[dict]:
    """Check that every browser destination resolves to a shipped panel."""
    root = Path(root)
    panel_folders = {
        "daily_run": "audit_web_assets",
        "run_doc_editor": "run_doc_editor_web_assets",
        "snapshot": "snapshot_web_assets",
        "job_notes": "job_notes_web_assets",
        "apa": "apa_web_assets",
        "disputes": "disputes_web_assets",
        "kpi": "kpi_web_assets",
        "photo_folders": "photo_folders_web_assets",
        "resources": "resources_web_assets",
        "cheat_sheet": "cheat_sheet_web_assets",
        "settings": "settings_web_assets",
    }
    rows = []
    for key, item in _TOOLS.items():
        url = item["browser_url"]
        panel = ""
        if "panel=" in url:
            panel = url.split("panel=", 1)[1].split("&", 1)[0]
        target = root / panel_folders[panel] / "index.html" if panel else root / "home_web_assets" / "index.html"
        rows.append({"key": key, "ok": target.is_file(), "target": str(target)})
    return rows
