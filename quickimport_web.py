"""Quick Import — a stripped-down standalone tool for general office users.

Search-first: type a job name, pick it, and get a small set of friendly
buttons (import photos, stage for XA, open folder/Trello/XA/CompanyCam, copy
name/claim#/email/path, find/change folder, re-audit). No audit chrome, no
estimate/tracker power-tools.

It reuses the full app's proven backend wholesale by delegating to an internal
`audit_web.Api` (same pattern the Snapshot panel uses via `_aw()`), so every
action behaves identically to the main app — this file only adds the unified
search + a safe "create the job folder" fallback.

Launched as its own window from the same exe via `--quickimport` (see
home_web.py), so simple users get a dedicated shortcut and never see the
full launcher.
"""
from __future__ import annotations
import os
import sys

import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config
import paths

# RESOURCE_DIR = _MEIPASS in the frozen build (where bundled datas live),
# the scripts dir in dev — so assets resolve in both. We point the window at a
# bundle-ROOT shim and serve via http_server, so the UI page's `../web_shared/*`
# script includes resolve (file:// can't traverse up reliably in WebView2).
ROOT_HTML = os.path.join(paths.RESOURCE_DIR, "_quickimport_root.html")


def _canon(s: str) -> str:
    return " ".join((s or "").lower().split())


class Api:
    def __init__(self):
        self._window = None
        self._aw_singleton = None

    def attach(self, w):
        self._window = w

    def track_events(self, events):
        """Privacy-safe usage sink for the standalone Quick Import window."""
        try:
            import usage_tracker as _ut
            return _ut.record(events or [])
        except Exception as ex:
            return {"ok": False, "written": 0, "error": str(ex)}

    # ── Delegate to the full audit backend for all shared actions ────
    def _aw(self):
        import audit_web as _aw_mod
        if self._aw_singleton is None:
            self._aw_singleton = _aw_mod.Api()
            try:
                self._aw_singleton.attach(self._window)
            except Exception:
                pass
        return self._aw_singleton

    # ── Job search — FOLDER-FIRST (import targets), Trello fallback ──
    def search_jobs(self, query: str) -> dict:
        """Search jobs matching `query`, folder-first.

        Primary results are current-year job FOLDERS — the real import
        targets — matched on any word (so "robles" or "lilia" both find
        "Robles Lilia - 7.19.26"). Each folder job's Trello card / claim# /
        XA resolve on demand when a button is clicked (by name, same as the
        main app), so we never dump noisy card results next to real jobs.

        Only when NO folder matches do we fall back to Trello cards, tagged
        `has_folder:false` — those drive the 'create this job folder' path.
        `mode` tells the UI which case it's in."""
        q = _canon(query)
        if len(q) < 2:
            return {"ok": True, "results": [], "mode": "empty"}
        # Token match (order-independent) like the main audit: every word you
        # typed must appear in the folder name, in ANY order — so "kim
        # martinez" finds the "Martinez Kim" folder.
        qtokens = [t for t in q.split() if t]

        def _hit(name):
            nl = _canon(name)
            return all(t in nl for t in qtokens)

        seen: set[str] = set()

        folders = []
        try:
            cands = self._aw().list_folder_candidates("", "") or {}
            for c in (cands.get("candidates") or []):
                name = c.get("name") or ""
                if not _hit(name):
                    continue
                k = _canon(name)
                if k in seen:
                    continue
                seen.add(k)
                fpath = c.get("path") or ""
                folders.append({
                    "name": name, "display": name,
                    "folder_path": fpath,
                    "has_folder": True, "is_unit": False, "parent": "",
                    "card_id": "", "year_folder": c.get("year_folder") or "",
                })
                # Also surface each Unit/room subfolder as its own pickable row
                # so you can import straight into a specific unit (e.g. Lilia
                # Robles › Unit 1016).
                try:
                    import multi_unit_logic as _mu
                    for u in (_mu.list_unit_subfolders(fpath) or []):
                        uk = _canon(name + " " + (u.get("name") or ""))
                        if uk in seen:
                            continue
                        seen.add(uk)
                        folders.append({
                            "name":        name + " :: " + (u.get("name") or ""),
                            "display":     name + " › " + (u.get("name") or ""),
                            "folder_path": u.get("path") or "",
                            "has_folder":  True, "is_unit": True, "parent": name,
                            "card_id": "", "year_folder": c.get("year_folder") or "",
                        })
                except Exception:
                    pass
        except Exception:
            pass
        if folders:
            # Keep each property's units grouped right under it.
            folders.sort(key=lambda r: ((r.get("parent") or r["name"]).lower(),
                                        r.get("is_unit", False), r["name"].lower()))
            return {"ok": True, "results": folders[:60], "mode": "folders"}

        # No folder → Trello cards as "no folder yet" candidates.
        cards = []
        try:
            import trello_client as tc
            for card in (tc.find_cards_by_name(query, max_results=15) or []):
                name = card.get("name") or ""
                if not name or not _hit(name):
                    continue
                base = name.split(" - ")[0].strip()
                k = _canon(base)
                if k in seen:
                    continue
                seen.add(k)
                cards.append({
                    "name": base, "display": name,
                    "folder_path": "", "has_folder": False,
                    "card_id": card.get("card_id") or "", "year_folder": "",
                })
        except Exception:
            pass
        return {"ok": True, "results": cards[:20],
                "mode": "cards_no_folder" if cards else "none"}

    def select_job(self, name: str) -> dict:
        """Resolve one job to a full audit row (path, card, found, etc.) so
        the shared action modals + buttons behave exactly like the main app."""
        if not name:
            return {"ok": False, "error": "no job"}
        try:
            res = self._aw().reaudit_one(name)
            if res and res.get("ok"):
                return {"ok": True, "row": res.get("row") or {}}
            return {"ok": False, "error": (res or {}).get("error") or "not found"}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Create the job folder (safe fallback when nothing matched) ───
    def create_job_folder(self, name: str) -> dict:
        """Create a current-year job folder skeleton (EMS/PICS + EMS/DOCS) so
        a brand-new job can receive an import. Refuses if a same-named folder
        already exists (no dupes)."""
        clean = " ".join((name or "").split()).strip(" .-")
        if not clean:
            return {"ok": False, "error": "Enter a job name first"}
        # Windows-illegal chars out.
        import re as _re
        clean = _re.sub(r'[\\/:*?"<>|]', "-", clean)
        try:
            cfg = config.load()
            base = (cfg.get("audit_base") or "").strip()
        except Exception:
            base = ""
        if not base or not os.path.isdir(base):
            return {"ok": False, "error": "audit_base not configured"}
        # Find the current-year "<YYYY> Jobs" folder.
        import datetime as _dt
        yr = str(_dt.date.today().year)
        year_dir = ""
        try:
            with os.scandir(base) as it:
                for e in it:
                    if (e.is_dir(follow_symlinks=False) and yr in e.name
                            and "fire" not in e.name.lower()):
                        year_dir = e.path
                        break
        except OSError as ex:
            return {"ok": False, "error": f"scan error: {ex}"}
        if not year_dir:
            return {"ok": False, "error": f"No '{yr} Jobs' folder found"}
        job_dir = os.path.join(year_dir, clean)
        if os.path.isdir(job_dir):
            return {"ok": False, "error": "A folder with that name already "
                                          "exists — search for it instead.",
                    "exists": True, "path": job_dir}
        try:
            # Skeleton the importers assume.
            os.makedirs(os.path.join(job_dir, "EMS", "PICS"), exist_ok=False)
            os.makedirs(os.path.join(job_dir, "EMS", "DOCS"), exist_ok=True)
        except OSError as ex:
            return {"ok": False, "error": f"create failed: {ex}"}
        # Pin it so the resolver finds it immediately.
        try:
            import persistence
            persistence.set_folder_path(clean, job_dir)
        except Exception:
            pass
        return {"ok": True, "path": job_dir, "name": clean}

    def department(self) -> dict:
        try:
            return {"ok": True, "dept": (config.active_department() or "")}
        except Exception:
            return {"ok": True, "dept": ""}

    # ── Explicit passthroughs (pywebview only binds declared methods) ─
    # Each forwards to the full audit backend so behavior is identical.
    def open_od_for_client(self, client, path=""):
        return self._aw().open_od_for_client(client, path)
    def open_folder(self, path):
        return self._aw().open_folder(path)

    def file_preview(self, path, max_px=1400):
        return self._aw().file_preview(path, max_px)

    def od_summary(self, path, max_dirs=40):
        return self._aw().od_summary(path, max_dirs)

    def companycam_plan_tags(self, *a, **k):
        return self._aw().companycam_plan_tags(*a, **k)

    def companycam_apply_tags(self, *a, **k):
        return self._aw().companycam_apply_tags(*a, **k)

    def od_contents(self, path):
        return self._aw().od_contents(path)
    def open_trello_card(self, card_id):
        return self._aw().open_trello_card(card_id)
    def open_xa_link(self, client, card_id=""):
        return self._aw().open_xa_link(client, card_id)
    def open_companycam_link(self, client):
        return self._aw().open_companycam_link(client)
    def open_workcenter(self):
        return self._aw().open_workcenter()
    def get_claim_number(self, client):
        return self._aw().get_claim_number(client)
    def get_address(self, client):
        return self._aw().get_address(client)
    def reaudit_one(self, client):
        return self._aw().reaudit_one(client)
    def list_folder_candidates(self, client, year=""):
        return self._aw().list_folder_candidates(client, year)
    def list_subfolders(self, path):
        return self._aw().list_subfolders(path)
    def list_year_folders(self):
        return self._aw().list_year_folders()
    def pin_folder(self, client, path):
        return self._aw().set_folder_path(client, path)
    def set_folder_path(self, *a, **k):
        return self._aw().set_folder_path(*a, **k)
    def clear_folder_path(self, client):
        return self._aw().clear_folder_path(client)
    # Import (auto-split by stage/day) + native multi-file pick.
    def do_import(self, *a, **k):
        return self._aw().do_import(*a, **k)
    def do_import_grouped(self, *a, **k):
        return self._aw().do_import_grouped(*a, **k)
    def pick_and_import_file(self, *a, **k):
        return self._aw().pick_and_import_file(*a, **k)
    # Stage-for-XA modal (shared audit_detail.js) backend.
    def list_techs(self):
        return self._aw().list_techs()
    def list_pics_stages(self, client):
        return self._aw().list_pics_stages(client)
    def copy_pics_to_clipboard(self, client, stage=""):
        return self._aw().copy_pics_to_clipboard(client, stage)
    # Trello-attachments modal (shared) backend.
    def list_card_attachments(self, *a, **k):
        return self._aw().list_card_attachments(*a, **k)
    def download_card_attachments(self, *a, **k):
        return self._aw().download_card_attachments(*a, **k)
    def fetch_trello_image(self, *a, **k):
        return self._aw().fetch_trello_image(*a, **k)

    # ── Small helpers unique to the mini tool ───────────────────────
    def set_clipboard(self, text):
        try:
            import web_helpers
            return bool(web_helpers.set_clipboard_text(text or ""))
        except Exception:
            return False

    def open_url(self, url):
        try:
            import dept_browser
            if url:
                return dept_browser.open_url(url)
        except Exception:
            pass
        return False

    def resolve_card(self, client: str) -> dict:
        """Auto-resolve + PIN the job's Trello card.

        - Already pinned → return it.
        - Exactly one card whose name matches the job (order-independent) →
          auto-pin it.
        - Only one candidate at all → auto-pin it.
        - Several plausible cards → return them for a picker (needs_choice).
        - None → card_id "" (the name-based buttons still try on click)."""
        if not client:
            return {"ok": True, "card_id": "", "source": "none"}
        try:
            import persistence
            import trello_client as tc
        except Exception:
            return {"ok": True, "card_id": "", "source": "none"}

        pinned = persistence.get_trello_card_id(client) or ""
        if pinned:
            return {"ok": True, "card_id": pinned, "source": "pinned"}

        def _tok_key(s):
            return " ".join(sorted(_canon((s or "").split(" - ")[0]).split()))

        want = _tok_key(client)
        cands, seen = [], set()
        try:
            for c in (tc.find_cards_by_name(client, max_results=20) or []):
                cid = c.get("card_id") or ""
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                cands.append({
                    "card_id": cid,
                    "name": c.get("name") or "",
                    "board": c.get("board") or "",
                    "lane": c.get("list_name") or c.get("lane") or "",
                })
        except Exception:
            cands = []

        if not cands:
            return {"ok": True, "card_id": "", "source": "none"}

        exact = [c for c in cands if _tok_key(c["name"]) == want]
        pick = None
        if len(exact) == 1:
            pick = exact[0]
        elif len(cands) == 1:
            pick = cands[0]
        if pick:
            try:
                persistence.set_trello_card_ids(client, [pick["card_id"]])
            except Exception:
                pass
            return {"ok": True, "card_id": pick["card_id"], "source": "auto"}

        return {"ok": True, "needs_choice": True, "candidates": cands[:12]}

    def pin_card(self, client: str, card_id: str) -> dict:
        """Pin the chosen card to the job."""
        try:
            import persistence
            persistence.set_trello_card_ids(client, [card_id])
            return {"ok": True, "card_id": card_id}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_job_email(self, client, card_id="") -> dict:
        return self._aw().get_job_email(client, card_id)

    def job_admin_suggest(self, *a, **k):
        return self._aw().job_admin_suggest(*a, **k)

    def job_delete_preview(self, *a, **k):
        return self._aw().job_delete_preview(*a, **k)

    def job_delete_apply(self, *a, **k):
        return self._aw().job_delete_apply(*a, **k)

    def job_merge_preview(self, *a, **k):
        return self._aw().job_merge_preview(*a, **k)

    def job_merge_apply(self, *a, **k):
        return self._aw().job_merge_apply(*a, **k)


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Quick Import — SERVPRO EMS",
        url=ROOT_HTML, js_api=api,
        width=560, height=780, min_size=(440, 560))
    api.attach(win)
    # http_server roots at ROOT_HTML's dir (bundle root) so quickimport_web_assets/
    # and web_shared/ are both reachable — same setup home_web uses.
    webview.start(debug=False, http_server=True)


if __name__ == "__main__":
    main()
