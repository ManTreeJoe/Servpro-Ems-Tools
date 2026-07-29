"""Multi-Unit — Pywebview spike (read-only)."""
from __future__ import annotations
import os, sys
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)
import multi_unit_gui as mu

ASSETS_DIR = os.path.join(_HERE, "multi_unit_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def list_groups(self):
        try:
            props = mu.discover_multi_unit_properties() or []
        except Exception:
            return []
        out = []
        for p in props:
            # discover_multi_unit_properties returns parent_path / parent_name
            # / year / units. (Earlier this read p["path"]/p["client"] which
            # never existed, so the panel showed nothing.)
            ppath = p.get("parent_path") or ""
            try:
                units = mu.list_subjob_folders(ppath) or []
            except Exception:
                units = []
            out.append({
                "parent_canon": p.get("parent_name") or "",
                "path":         ppath,
                "year":         p.get("year"),
                "units": [{
                    "name":        u.get("name") or "",
                    "path":        u.get("path") or "",
                    "kind":        u.get("kind") or "unit",
                    # numeric unit label for Unit/Apt folders; "" for named
                    # sub-jobs (school/site/date folders).
                    "unit_number": ("" if (u.get("num") or 10**9) >= 10**9
                                     else u.get("num")),
                } for u in units],
            })
        return out

    def open_subjob_folder(self, path: str) -> bool:
        """Open a specific sub-job / unit folder by its absolute path
        (named sub-jobs have no unit number to match on)."""
        if path and os.path.isdir(path):
            try:
                os.startfile(path); return True
            except Exception:
                return False
        return False

    def open_unit_folder(self, parent_path: str, unit_number: str):
        """Open the folder for a specific unit. Picks the deepest
        unit subfolder matching `unit_number` so the user lands in
        the right place even on properties where the unit folder is
        nested under the property root."""
        if not parent_path or not os.path.isdir(parent_path):
            return False
        try:
            units = mu.list_unit_subfolders(parent_path) or []
        except Exception:
            units = []
        for u in units:
            if str(u.get("unit_number") or "") == str(unit_number):
                p = u.get("path") or ""
                if p and os.path.isdir(p):
                    try: os.startfile(p); return True
                    except Exception: return False
        # Fallback: open the parent
        try: os.startfile(parent_path); return True
        except Exception: return False

    def open_parent_folder(self, parent_path: str):
        if parent_path and os.path.isdir(parent_path):
            try: os.startfile(parent_path); return True
            except Exception: return False
        return False

    # ── Tk parity: cleanup dry-run + apply ──────────────────────────
    def cleanup_dry_run(self) -> dict:
        """Walk the audit base for multi-unit properties + propose
        rename actions for unit subfolders that need normalizing.
        Mirrors `multi_unit_cleanup.py` — dry-run only; the user must
        explicitly call `cleanup_apply(...)` to execute."""
        try:
            import multi_unit_cleanup as muc
            import paths, datetime
            base = paths.audit_base()
            # Current year only — never rename closed-out historical-year
            # folders (matches the CLI default; audit bug #1). The web
            # panel used to omit year_filter and walk every <YYYY> Jobs\.
            reports = muc.find_multi_unit_properties(
                base, year_filter=datetime.date.today().year) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "properties": []}
        out = []
        total_renames = 0
        for rep in reports:
            try:
                renames = muc.propose_renames_for(rep.path) or []
            except Exception:
                renames = []
            items = []
            for r in renames:
                # Drop no-op / already-canonical / skip rows so the preview
                # count isn't inflated with blank-target rows (finding #8).
                if getattr(r, "skip", False) or not r.dst or r.dst == r.src:
                    continue
                items.append({
                    "src":      r.src,
                    "dst":      r.dst,
                    "name":     os.path.basename(r.src),
                    "new_name": os.path.basename(r.dst),
                })
            if not items:
                continue
            out.append({
                "property": os.path.basename(rep.path),
                "path":     rep.path,
                "renames":  items,
            })
            total_renames += len(items)
        return {"ok": True, "properties": out,
                "total_renames": total_renames}

    def cleanup_apply(self, selected: list = None) -> dict:
        """Execute exactly the renames the user previewed.

        `selected` is a list of {"src","dst"} pairs (the rows checked in
        the dialog) — executed verbatim rather than re-proposed, so a
        Trello Date-Received change between preview and apply can't
        silently retarget a rename to a destination the user never saw
        (audit bug #3). A legacy list of src strings falls back to the
        current-year re-propose path."""
        try:
            import multi_unit_cleanup as muc
            pairs = []
            for item in (selected or []):
                if (isinstance(item, dict)
                        and item.get("src") and item.get("dst")):
                    pairs.append((item["src"], item["dst"]))
            if pairs:
                renames = [muc.Rename(src=s, dst=d, reason="user-approved")
                           for s, d in pairs]
            else:
                # Legacy src-string list → re-derive (current year only).
                import paths, datetime
                base = paths.audit_base()
                picked = set(selected or [])
                reports = muc.find_multi_unit_properties(
                    base, year_filter=datetime.date.today().year) or []
                renames = []
                for rep in reports:
                    try:
                        rs = muc.propose_renames_for(rep.path) or []
                    except Exception:
                        continue
                    for r in rs:
                        if (getattr(r, "skip", False)
                                or not r.dst or r.dst == r.src):
                            continue
                        if picked and r.src not in picked:
                            continue
                        renames.append(r)
            if not renames:
                return {"ok": False, "error": "Nothing to rename"}
            result = muc.execute_renames(renames, dry_run=False) or {}
            # execute_renames returns renamed/skipped/failed/events — map
            # to the moved/errors the UI reads (audit bug #2: the old code
            # read nonexistent 'moved'/'errors' keys, always showing 0).
            fail_events = [
                f"{os.path.basename(s)}: {msg}"
                for (s, _d, status, msg) in result.get("events", [])
                if status in ("FAIL", "CONFLICT")]
            return {"ok": True,
                    "moved":  int(result.get("renamed") or 0),
                    "errors": fail_events}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Multi-Unit — EMS Tools (web)",
        url=INDEX_HTML, js_api=api,
        width=1100, height=820, min_size=(640, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
