"""Photo Folders — Pywebview spike.

Creates SharePoint photo folders for every (tech, client) pair in
today's run-doc. Reuses `daily_photos_gui.make_folders` so the
folder-naming + tech-root resolution logic is identical to the Tk
version — no fork.
"""
from __future__ import annotations
import datetime as _dt
import os, sys
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import daily_photos_gui as dp

ASSETS_DIR = os.path.join(_HERE, "photo_folders_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def find_run_doc_for(self, day_offset: int = 0) -> dict:
        """Lookup helper for the day-walker UI. Returns the resolved
        date + whether a run-doc exists for that day. Mirrors the
        audit panel's `find_run_doc_for` so the UI can show the same
        kind of date label + Open run-doc button."""
        try:
            import run_audit_gui as _rag
            offset = int(day_offset or 0)
            d = _dt.date.today() + _dt.timedelta(days=offset)
            doc = _rag._find_run_doc_for_date(d)
            return {
                "ok":         True,
                "date_iso":   d.strftime("%Y-%m-%d"),
                "date_label": d.strftime("%A %m/%d/%Y"),
                "date_short": d.strftime("%m-%d-%y"),
                "doc_path":   doc or "",
                "exists":     bool(doc and os.path.isfile(doc)),
                "is_today":   offset == 0,
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_run_doc(self, day_offset: int = 0) -> bool:
        try:
            import run_audit_gui as _rag
            d = _dt.date.today() + _dt.timedelta(days=int(day_offset or 0))
            doc = _rag._find_run_doc_for_date(d)
            if doc and os.path.isfile(doc):
                os.startfile(doc); return True
        except Exception:
            pass
        return False

    def today_jobs(self, day_offset: int = 0):
        """Run-doc jobs for the chosen day (offset relative to today,
        negative = earlier days). Returns each job with its detected
        techs + folder-exists status so the UI can color-code rows."""
        try:
            import run_audit_gui as _rag
            from state_hub import hub as _sh
            offset = int(day_offset or 0)
            d = _dt.date.today() + _dt.timedelta(days=offset)
            doc = _rag._find_run_doc_for_date(d)
            if not doc:
                return {"ok": False,
                        "error": f"no run-doc for {d.strftime('%A %m/%d/%Y')}",
                        "date_iso": d.strftime("%Y-%m-%d"),
                        "date_label": d.strftime("%A %m/%d/%Y")}
            jobs, run_date = _sh.parse_run_doc(doc)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        run_date_str = run_date.strftime("%m-%d-%y") if hasattr(run_date, "strftime") else str(run_date)
        from audit_logic import detect_activity as _detect_activity
        out = []
        for j in jobs:
            client = j.get("client") or ""
            techs = list(j.get("techs") or [])
            tech_status = []
            for t in techs:
                # Check if folder already exists for this (tech, date, client)
                try:
                    existing = dp._photo_folder_path(t, run_date_str, client)
                except Exception:
                    existing = None
                tech_status.append({
                    "tech":    t,
                    "exists":  bool(existing),
                    "path":    existing or "",
                })
            # Mirror Tk's daily_photos_gui activity badge — "demo · mit"
            # plus "expects: Demo pics, Initial pics" hint. Without this
            # the user can't tell at a glance what the techs are doing
            # for each job before checking folders to create.
            try:
                activity = _detect_activity(j.get("raw") or "",
                                            j.get("section"),
                                            bool(j.get("new_loss")))
            except Exception:
                activity = {"labels": [], "needs_photos": True, "expected": []}
            out.append({
                "client":     client,
                "techs":      techs,
                "tech_status": tech_status,
                "section":    j.get("section") or "work",
                "raw":        j.get("raw") or "",
                "new_loss":   bool(j.get("new_loss")),
                "all_exist":  all(s["exists"] for s in tech_status) if tech_status else False,
                "activity_labels":  list(activity.get("labels") or []),
                "needs_photos":     bool(activity.get("needs_photos")),
                "expected_folders": list(activity.get("expected") or []),
            })
        return {"ok": True, "rows": out, "run_date": run_date_str,
                "day_offset": offset,
                "date_iso": d.strftime("%Y-%m-%d"),
                "run_date_label": run_date.strftime("%A %m/%d/%Y") if hasattr(run_date, "strftime") else str(run_date)}

    def create_folders(self, selections, day_offset: int = 0):
        """Create photo folders for the selected (tech, client) pairs
        on the chosen day (offset relative to today). Negative offset
        = earlier days — common case: making folders the morning after
        for yesterday's run.

        `selections` is a list of {"client": str, "techs": [str, ...]}.
        Lets the user skip specific techs within a job — e.g. job has
        3 techs but only 2 should get photo folders. Mirrors the Tk
        flow but adds per-tech granularity.

        Returns a summary of created vs skipped, with the same
        message format `daily_photos_gui.make_folders` produces.
        """
        try:
            import run_audit_gui as _rag
            from state_hub import hub as _sh
            d = _dt.date.today() + _dt.timedelta(days=int(day_offset or 0))
            doc = _rag._find_run_doc_for_date(d)
            if not doc:
                return {"ok": False,
                        "error": f"no run-doc for {d.strftime('%A %m/%d/%Y')}"}
            jobs, run_date = _sh.parse_run_doc(doc)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        run_date_str = run_date.strftime("%m-%d-%y") if hasattr(run_date, "strftime") else str(run_date)
        # Build {client: set(techs_to_include)} from the selection.
        want = {}
        for s in (selections or []):
            c = (s.get("client") or "").strip()
            if not c: continue
            want[c] = set(s.get("techs") or [])
        if not want:
            return {"ok": False, "error": "no selections"}
        # Build a synthetic jobs list where each job's `techs` is
        # filtered to ONLY the selected techs. dp.make_folders walks
        # the techs list per job, so this is the surgical hook for
        # per-tech selection.
        target = []
        for j in jobs:
            client = (j.get("client") or "").strip()
            if client not in want: continue
            selected_techs = want[client]
            if not selected_techs: continue
            filtered_techs = [t for t in (j.get("techs") or [])
                              if t in selected_techs]
            if not filtered_techs: continue
            target.append({
                "client": client,
                "techs":  filtered_techs,
            })
        if not target:
            return {"ok": False, "error": "no techs selected"}
        try:
            created, skipped = dp.make_folders(target, run_date_str)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "created": created, "skipped": skipped,
                "run_date": run_date_str}

    def open_folder(self, path):
        if not path or not os.path.isdir(path):
            return False
        try: os.startfile(path); return True
        except Exception: return False


    # ── 🗑 Cleanup empty SP folders (mirrors daily_photos_gui.py:764) ──
    # Walks every tech's SharePoint job folder, surfaces ones with zero
    # photos, and lets the user send selected ones to the Recycle Bin.
    # Recycle-bin delete only (via send2trash) — never hard-delete.
    def scan_empty_sp_folders(self) -> dict:
        """Run sharepoint.find_empty_photo_folders and return shaped
        rows the frontend can render directly. Each row has name,
        tech, path, mtime, age_days."""
        try:
            import sharepoint as _sp
            rows = _sp.find_empty_photo_folders() or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "rows": []}
        out = []
        techs = set()
        for r in rows:
            tech = r.get("tech") or ""
            if tech: techs.add(tech)
            out.append({
                "name":      r.get("name") or os.path.basename(r.get("path") or ""),
                "tech":      tech,
                "path":      r.get("path") or "",
                "mtime":     r.get("mtime") or "",
                "age_days":  int(r.get("age_days") or 0),
            })
        return {"ok": True, "rows": out,
                "techs": sorted(techs),
                "total": len(out)}

    def delete_empty_sp_folders(self, paths: list) -> dict:
        """Send selected SharePoint folder paths to the Recycle Bin.
        Uses send2trash (recoverable). Hard delete is intentionally
        unavailable from this dialog — matches Tk's safety policy
        (daily_photos_gui.py:996)."""
        if not paths:
            return {"ok": False, "error": "no paths"}
        try:
            from send2trash import send2trash
        except Exception as ex:
            return {"ok": False,
                    "error": f"send2trash unavailable: {ex} — hard delete "
                             "is intentionally not exposed"}
        deleted, failed = [], []
        for p in paths:
            try:
                send2trash(p)
                deleted.append(p)
            except Exception as ex:
                failed.append({"path": p, "error": str(ex)})
        return {"ok": True, "deleted": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed)}

    def find_od_for_sp_name(self, sp_folder_name: str) -> str:
        """Resolve the OneDrive job folder for a SharePoint folder
        name (e.g. 'Smith 5-22-26 Demo' → 'X:\\IE_Public\\2026 Jobs\\Smith').
        Mirrors daily_photos_gui._find_od_folder_for_client. Used by
        the 📁 OD button per row in the cleanup dialog."""
        try:
            import daily_photos_gui as _dpg
            client = _dpg._client_from_sp_name(sp_folder_name) or ""
            if not client:
                return ""
            return _dpg._find_od_folder_for_client(client) or ""
        except Exception:
            return ""


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Photo Folders — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=1100, height=820, min_size=(640, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
