"""Spreadsheet — Pywebview spike (workbook launcher)."""
from __future__ import annotations
import os, sys
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)
import workbook_registry as wbr
from web_helpers import run_bg as _wh_run_bg

# The workbook specs (Snapshots, Disputes, …) are registered as a
# side-effect of importing `spreadsheet_gui` at module load. Without
# this import the web panel renders an empty list because the
# registry is never populated. The import only pulls in module-level
# definitions — no Tk windows are created.
try:
    import workbook_specs  # noqa: F401 — registers the specs; NOT the Tk panel
except Exception:
    pass
# User-added workbooks (saved via spreadsheet_gui's "+ Add workbook"
# UI) live in user_workbooks.json. Importing the module triggers
# register_all() at module-level so they're picked up too.
try:
    import user_workbooks  # noqa: F401 — side-effect: register_all()
except Exception:
    pass

ASSETS_DIR = os.path.join(_HERE, "spreadsheet_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def workbooks(self):
        """Return every registered workbook with its resolved file path.
        WorkbookSpec carries `label` (display name) + `workbook_path`
        (a callable taking the year); we don't auto-discover the
        year so default to today's.

        Also flags whether each entry was user-added (via the ➕ Add
        Workbook dialog) vs. built-in so the sidebar can show a
        ✕ Remove button on the user-added ones.
        """
        try:
            import datetime as _dt
            year = _dt.date.today().year
            # Build set of user-added keys for the is_user flag.
            try:
                import user_workbooks as _uwb
                user_keys = {(e.get("key") or "").strip()
                              for e in (_uwb.list_entries() or [])}
            except Exception:
                user_keys = set()
            out = []
            for spec in wbr.all_specs():
                path = ""
                try:
                    wp = getattr(spec, "workbook_path", None)
                    if callable(wp):
                        path = wp(year) or ""
                    elif isinstance(wp, str):
                        path = wp
                except Exception:
                    path = ""
                key = getattr(spec, "key", "")
                out.append({
                    "key":    key,
                    "name":   getattr(spec, "label", "") or key,
                    "path":   path,
                    "exists": bool(path and os.path.isfile(path)),
                    "is_user": key in user_keys,
                })
            return out
        except Exception as ex:
            # Surface the error to the JS console instead of returning
            # an empty list silently (the bug that made the panel blank).
            return [{"key": "_err", "name": f"Registry error: {ex}",
                     "path": "", "exists": False}]

    def view_workbook(self, key: str, year: int = 0) -> dict:
        """Render a workbook's contents for the in-app table viewer.
        Mirrors what `spreadsheet_gui._refresh` + `_redraw` build:
        spec.read_rows(year) → list of dicts, each shaped via
        spec.row_to_values + spec.tag_for_row + spec.search_blob.
        Returns columns + rows + sheets so the frontend can render
        a sortable / filterable table with tag-colored rows.
        """
        if not key:
            return {"ok": False, "error": "no key"}
        try:
            import datetime as _dt
            spec = wbr.get(key)
            if spec is None:
                return {"ok": False, "error": f"unknown workbook key: {key}"}
            yr = int(year) if year else _dt.date.today().year
            rows = spec.read_rows(yr) or []
        except Exception as ex:
            return {"ok": False, "error": f"read failed: {ex}"}
        # Columns from the spec — list of ColumnSpec dataclass
        cols = []
        try:
            for c in (spec.columns or []):
                cols.append({
                    "label": getattr(c, "label", "") or "",
                    "width": int(getattr(c, "width", 0) or 0),
                    "anchor": getattr(c, "anchor", "") or "w",
                })
        except Exception:
            cols = []
        # Sheet filter values
        sheets = []
        try:
            sheets = list(spec.sheets or [])
        except Exception:
            sheets = []
        # Tag → color mapping (CSS hex strings from the spec.tag_colors)
        tag_colors = {}
        try:
            for k, v in (spec.tag_colors or {}).items():
                tag_colors[str(k)] = str(v)
        except Exception:
            tag_colors = {}
        # Shape every row through row_to_values + tag_for_row so the
        # table renders the same as Tk.
        out_rows = []
        for r in rows:
            try:
                values = spec.row_to_values(r) or ()
                tag = spec.tag_for_row(r) or ""
                # search_blob is used for client-side filtering — same
                # behavior the Tk redraw uses for text-filter match.
                blob = ""
                try:
                    getter = getattr(spec, "search_blob", None)
                    if callable(getter):
                        blob = (getter(r) or "").lower()
                except Exception:
                    pass
                out_rows.append({
                    "values":  [str(v) if v is not None else "" for v in values],
                    "tag":     tag,
                    "sheet":   str(r.get("_sheet") or ""),
                    "blob":    blob,
                })
            except Exception:
                # Skip individual bad rows so a single broken row
                # doesn't break the whole viewer
                continue
        # Workbook path for the status bar
        path = ""
        try:
            wp = getattr(spec, "workbook_path", None)
            if callable(wp):
                path = wp(yr) or ""
            elif isinstance(wp, str):
                path = wp
        except Exception:
            pass
        return {
            "ok":         True,
            "key":        key,
            "label":      getattr(spec, "label", key) or key,
            "year":       yr,
            "path":       path,
            "columns":    cols,
            "sheets":     sheets,
            "tag_colors": tag_colors,
            "rows":       out_rows,
            "total":      len(out_rows),
        }

    def open_file(self, path):
        if not path or not os.path.isfile(path): return False
        try: os.startfile(path); return True
        except Exception: return False

    # ── Snapshots workbook utilities (mirrors Tk's spreadsheet_gui) ──
    def dedupe_snapshots_workbook(self, year=None, dry_run=True):
        """Group dupes in the Snapshots <YY>.xlsx workbook by canonical
        name key and merge them. Defaults to dry-run preview."""
        try:
            import snapshots_excel as se
            import datetime as _dt
            yr = int(year) if year else _dt.date.today().year
            result = se.dedupe_workbook(yr, dry_run=bool(dry_run))
            return {"ok": True, "year": yr,
                    "groups": result.get("groups", []),
                    "rows_removed": result.get("rows_removed", 0),
                    "errors": result.get("errors", []),
                    "dry_run": bool(dry_run)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def reconcile_snapshots_with_trello(self, year=None):
        """Cross-check every Snapshots-workbook row against its Trello
        card and surface drift (closed cards still marked open, etc).
        Background-thread version with an event push so the UI can
        stream progress."""
        try:
            import snapshots_excel as se
            import datetime as _dt
            yr = int(year) if year else _dt.date.today().year
            if getattr(self, "_reconcile_running", False):
                return {"started": False,
                        "reason": "reconcile already in progress"}
            self._reconcile_running = True

            def _bg():
                try:
                    import web_event
                    # Throttle per-row progress so the synchronous
                    # evaluate_js stream doesn't freeze the UI.
                    def _emit(label, done, total):
                        is_final = bool(total) and done >= total
                        web_event.throttled_event(
                            self._window, "recon:progress",
                            {"label": label, "done": done, "total": total},
                            final=is_final)
                    result = se.reconcile_with_trello(
                        yr, progress_cb=lambda *a: _emit(*a))
                    payload = {"ok": True, "result": result}
                except Exception as ex:
                    payload = {"ok": False, "error": str(ex)}
                finally:
                    self._reconcile_running = False
                try:
                    import web_event
                    web_event.event(self._window, "recon:done", payload)
                except Exception:
                    pass

            _wh_run_bg(_bg)
            return {"started": True, "year": yr}
        except Exception as ex:
            return {"started": False, "reason": str(ex)}

    def generate_daily_audit_md(self):
        """Produce the daily-audit Markdown notes file for today.
        Saves to the shared share if available; returns the path."""
        try:
            import audit_export, paths
            import datetime as _dt
            today = _dt.date.today().strftime("%Y-%m-%d")
            # Reuse audit_web's _last_rows when present so we don't
            # re-walk the drives. Falls back to an empty result file
            # when no audit has run.
            try:
                import audit_web
                rows = list(audit_web.Api()._last_rows or [])
            except Exception:
                rows = []
            out_dir = os.path.join(paths.DATA_DIR, "audit_exports")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"audit_{today}.md")
            md = audit_export.write_audit_md(rows, run_date=today) or ""
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(md)
            os.startfile(out_path)
            return {"ok": True, "path": out_path, "rows": len(rows)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


    # ── ➕ Add custom workbook flow ──────────────────────────────────
    # Mirrors Tk spreadsheet_gui.py:325 _open_add_workbook_dialog: pick
    # a file, inspect its sheets/headers, save the entry, then re-
    # register the registry so the new spec shows up in workbooks().
    def pick_workbook_file(self) -> dict:
        """Open the native file picker for .xlsx/.xlsm and return the
        path + auto-inspection result so the frontend can show a
        sheet/header confirm step."""
        try:
            picked = None
            if self._window is not None:
                # Pywebview gives us a native dialog tied to the host
                # window. file_types order matters — Excel formats
                # first so they're the default.
                res = self._window.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False,
                    file_types=("Excel workbooks (*.xlsx;*.xlsm)",
                                "All files (*.*)"))
                if res:
                    picked = res[0] if isinstance(res, (list, tuple)) else res
            if not picked:
                return {"ok": False, "canceled": True}
            import user_workbooks as _uwb
            info = _uwb.inspect_workbook(picked) or {}
            if not info.get("ok"):
                return {"ok": False, "error": info.get("error") or "Couldn't read workbook"}
            # Default label = filename without extension. Frontend can
            # override before save.
            default_label = os.path.splitext(os.path.basename(picked))[0]
            return {"ok": True, "path": picked, "info": info,
                    "default_label": default_label}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def inspect_workbook_at(self, path: str) -> dict:
        """Re-inspect a workbook (used when the user manually pastes a
        path or after a sheet/header_row change in the confirm step)."""
        try:
            import user_workbooks as _uwb
            info = _uwb.inspect_workbook(path) or {}
            return info
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def add_workbook(self, label: str, path: str,
                     sheet: str = "", header_row: int = 1) -> dict:
        """Persist the picked workbook to user_workbooks.json + re-
        register so it shows up in the sidebar immediately. Mirrors
        Tk spreadsheet_gui.py:478 _save."""
        if not (label or "").strip() or not (path or "").strip():
            return {"ok": False, "error": "label and path required"}
        try:
            import user_workbooks as _uwb
            entry = _uwb.add_entry(
                label=label.strip(), path=path.strip(),
                sheet=(sheet or "").strip(),
                header_row=int(header_row or 1))
            if not entry:
                return {"ok": False, "error": "save failed (check path + label)"}
            try: _uwb.register_all()
            except Exception: pass
            return {"ok": True, "entry": entry, "key": entry.get("key", "")}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def remove_workbook(self, key: str) -> dict:
        """Drop a user-added workbook entry. Re-registers afterwards
        so the sidebar refreshes."""
        if not (key or "").strip():
            return {"ok": False, "error": "key required"}
        try:
            import user_workbooks as _uwb
            ok = _uwb.remove_entry(key.strip())
            if ok:
                try: _uwb.register_all()
                except Exception: pass
            return {"ok": bool(ok)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Spreadsheets — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=900, height=720, min_size=(560, 400))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
