"""Initial Upload Queue — Pywebview panel.

Pulls cards from the same Trello lanes as the Tk IUQ + APA
Initial-Uploads section + manual rows, dedupes, and renders them in
a two-pane master/detail layout. Per-card actions: make folders,
import SP/WC, pin, comment, docusketch request, mark uploaded,
create Trello card from manual row, plus audit subview parity (form
+ photo issues, SP/WC import).
"""
from __future__ import annotations
import os, sys, threading, webbrowser
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import initial_upload_queue as iuq
import persistence
from web_helpers import run_bg as _wh_run_bg


ASSETS_DIR = os.path.join(_HERE, "iuq_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


_RUN_DOC_CACHE = {"date": None, "jobs": []}


def _today_run_doc_jobs():
    """Cached parse of today's run-doc — used by the time-slot pill.
    Cache invalidates per-day automatically."""
    import datetime as _dt
    today = _dt.date.today()
    if _RUN_DOC_CACHE["date"] == today:
        return _RUN_DOC_CACHE["jobs"]
    jobs = []
    try:
        from run_audit_gui import _find_run_doc_for_date, parse_run_doc
        path = _find_run_doc_for_date(today)
        if path:
            jobs, _ = parse_run_doc(path)
    except Exception:
        jobs = []
    _RUN_DOC_CACHE["date"] = today
    _RUN_DOC_CACHE["jobs"] = jobs or []
    return _RUN_DOC_CACHE["jobs"]


def _time_slot_for_client(client):
    """Find today's appointment time slot for `client` from the run-doc.
    Returns "" when there's no match. Mirrors the Tk IUQ lookup with
    case-insensitive + comma-swap-tolerant matching."""
    if not client: return ""
    import re
    def _norm(s):
        s = re.sub(r"[^a-z ,]", " ", (s or "").lower())
        s = re.sub(r"\s+", " ", s).strip()
        # comma-swap: "sanchez, jacqueline" → "jacqueline sanchez"
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2:
                s = f"{parts[1]} {parts[0]}".strip()
        return s
    target = _norm(client)
    if not target: return ""
    target_toks = set(t for t in target.split() if len(t) >= 2)
    for j in _today_run_doc_jobs():
        n = _norm(j.get("client") or "")
        if not n: continue
        if n == target:
            return (j.get("time_slot") or "").strip()
        # Token overlap fallback (handles initials, abbreviations,
        # trailing date suffixes on Trello cards)
        n_toks = set(t for t in n.split() if len(t) >= 2)
        if len(target_toks & n_toks) >= 2:
            return (j.get("time_slot") or "").strip()
    return ""


def _shape_row(c):
    """Flatten a raw IUQ card into the JSON shape the frontend uses.

    The Tk-side `_fetch_queue_from_trello` returns each card with a
    `checklists` list — one entry per tracked checklist (INITIAL -
    ADMIN, INITIAL), each with its own items. The old web `_shape_row`
    only looked at a top-level `items` key (which doesn't exist) so
    every card showed 0/0 progress + no checklist items.

    Now: expose both checklists in `checklists` AND a flat `items`
    list pooled from all of them so the existing renderers don't
    break. Progress counts the pooled items.
    """
    client = c.get("client") or ""
    raw_checklists = c.get("checklists") or []
    # Surface every tracked checklist so the UI can render multiple
    # groups when both INITIAL - ADMIN and INITIAL exist.
    checklists = []
    pooled = []
    for cl in raw_checklists:
        cl_items = []
        for it in (cl.get("items") or []):
            state_lower = (it.get("state") or "").lower()
            shaped = {
                "name":  it.get("name") or "",
                "done":  state_lower == "complete",
                "state": state_lower,  # "complete" / "incomplete" / "missing"
                "id":    it.get("id") or "",
            }
            cl_items.append(shaped)
            pooled.append(shaped)
        checklists.append({
            "name":    cl.get("name") or "",
            "id":      cl.get("id") or "",
            "present": bool(cl.get("present")),
            "items":   cl_items,
        })
    # Progress: count complete vs total ACROSS all tracked items
    done  = sum(1 for it in pooled if it["done"])
    total = len(pooled)
    # 📨 Requested chip — read the audit_comments table the Tk panel
    # uses. Pulls the most recent request-Initial-Photo-Report comment
    # date and returns days-ago so the JS can render a stale-since pill.
    requested_days = None
    requested_at = ""
    try:
        import persistence as _per
        import datetime as _dt
        last_iso = _per.get_audit_comment_date(client, "initial_photo_report") or ""
        if last_iso:
            try:
                d = _dt.date.fromisoformat(last_iso[:10])
                requested_days = (_dt.date.today() - d).days
                requested_at = last_iso[:10]
            except Exception:
                pass
    except Exception:
        pass
    return {
        "card_id":  c.get("card_id") or "",
        "client":   client,
        "name":     c.get("name") or "",
        "lane":     c.get("lane") or "",
        "card_url": c.get("shortUrl") or "",
        # Manual-add rows carry this flag so the UI shows the ✕ Remove
        # button and suppresses checklist rendering (no checklists on disk).
        "manual":   bool(c.get("manual")),
        "labels":   [str(l) for l in (c.get("labels") or [])],
        "checklists": checklists,
        # Flat pooled view for the legacy detail renderer
        "items":    pooled,
        "done":     done,
        "total":    total,
        "progress": f"{done}/{total}" if total else "—",
        "time_slot": _time_slot_for_client(client),
        # 📋 APA chip — Tk surfaces APA-synthesized rows with a
        # distinguishing badge so the user knows the entry came from
        # APA Monitor's Initial Uploads (vs the Trello scan path).
        "from_apa":  bool(c.get("from_apa")),
        # 📨 Requested chip — visible reminder that the user already
        # asked for the Initial Photo Report N days ago.
        "requested_days": requested_days,
        "requested_at":   requested_at,
    }


class Api:
    def __init__(self):
        self._window = None
        self._loading = False
        self._last_rows = []

    def attach(self, w): self._window = w

    def last_cards(self):
        return {"rows": list(self._last_rows), "lanes": _lanes()}

    def refresh(self):
        if self._loading: return {"started": False, "reason": "already refreshing"}
        self._loading = True

        def _bg():
            try:
                rows = iuq._fetch_queue_from_trello() or []
                shaped = [_shape_row(r) for r in rows]
                # Enrich every row with the audit's missing-items view.
                # User asked the IUQ to also surface what audit_jobs
                # flags as missing forms/photos so they can act on
                # both checklist + audit gaps from one panel.
                self._enrich_with_audit(shaped)
                self._last_rows = shaped
                self._emit_done(ok=True)
            except Exception as ex:
                self._emit_done(ok=False, error=f"{type(ex).__name__}: {ex}")
            finally:
                self._loading = False
        _wh_run_bg(_bg)
        return {"started": True}

    def _enrich_with_audit(self, rows):
        """Run audit_logic.audit_jobs for every IUQ row and attach the
        flagged forms/photos to the row. Quiet on miss — rows that
        don't resolve to a folder just stay empty so the UI degrades
        gracefully."""
        try:
            import audit_logic as _al
            import paths as _paths
            import datetime as _dt
            clients = [r.get("client") or "" for r in rows if r.get("client")]
            if not clients:
                return
            results, _err = _al.audit_jobs(
                clients, _paths.audit_base(),
                run_date=_dt.date.today(),
                use_cache=True) or ([], None)
            by_client = {}
            for res in (results or []):
                cn = (res.get("client") or "").strip()
                if cn: by_client[cn] = res
            for r in rows:
                cn = (r.get("client") or "").strip()
                res = by_client.get(cn) or {}
                r["audit_form_issues"]  = res.get("form_issues") or []
                r["audit_photo_issues"] = res.get("photo_issues") or []
                # Misfiled items — present elsewhere in a commercial
                # parent's tree (wrong folder), not missing. Mirrors the
                # audit + snapshot "misfiled" surface. Each: {label,where}.
                r["audit_misplaced_forms"]  = [
                    m for m in (res.get("misplaced_forms") or [])
                    if isinstance(m, dict)]
                r["audit_misplaced_photos"] = [
                    m for m in (res.get("misplaced_photos") or [])
                    if isinstance(m, dict)]
                r["audit_flagged"]      = bool(res.get("flagged"))
                r["audit_found"]        = bool(res.get("found"))
                r["audit_path"]         = res.get("path") or ""
                r["audit_total_missing"] = (
                    len(r["audit_form_issues"]) + len(r["audit_photo_issues"]))
                # SharePoint upload counter — surfaces "N files on SP
                # not yet in OD" so the IUQ row shows the same 📥 SP
                # +N chip the audit panel does. Audit logic populates
                # sharepoint_matches + sharepoint_new on every audit
                # row when SP discovery is enabled.
                sp_matches_raw = res.get("sharepoint_matches") or []
                r["sharepoint_matches"] = [{
                    "name":         m.get("name") or "",
                    "path":         m.get("path") or "",
                    "tech":         m.get("tech") or "",
                    "new_count":    int(m.get("new_count") or 0),
                    # Source dict uses "count" — see audit_web fix
                    # (Cindy Costales "21 new but 0 files" symptom).
                    "img_count":    int(m.get("img_count") or m.get("count") or 0),
                    "matches_date": bool(m.get("matches_date")),
                } for m in sp_matches_raw]
                r["sharepoint_new"] = int(res.get("sharepoint_new") or 0)
                # Audit path is also the job's OneDrive path — IUQ
                # uses it for the SP import target.
                r["path"] = res.get("path") or r.get("audit_path") or ""
        except Exception:
            # Non-fatal — IUQ keeps working even when audit fails.
            for r in rows:
                r.setdefault("audit_form_issues",  [])
                r.setdefault("audit_photo_issues", [])
                r.setdefault("audit_misplaced_forms",  [])
                r.setdefault("audit_misplaced_photos", [])
                r.setdefault("audit_flagged",       False)
                r.setdefault("audit_found",         False)
                r.setdefault("audit_path",          "")
                r.setdefault("audit_total_missing", 0)
                r.setdefault("sharepoint_matches",  [])
                r.setdefault("sharepoint_new",       0)
                r.setdefault("path",                "")

    def open_url(self, url):
        if not url: return False
        try: webbrowser.open(url); return True
        except Exception: return False

    # ── Per-row actions ──────────────────────────────────────────────
    def open_od(self, client):
        """Backward-compatible bool return. New IUQ JS uses
        open_od_for_client (richer return) — kept for any older
        right-click code paths that haven't migrated."""
        res = self.open_od_for_client(client, "")
        return bool(res.get("ok"))

    def open_od_for_client(self, client, hint_path=""):
        """Smart-open the OD folder. Delegates to audit_web's resolver
        chain so the IUQ + audit + snapshot all share the same logic
        (and the same fix for the stale-path bug — when a row's cached
        path is dead, this falls through to persistence and the
        validated row caches instead of failing silently)."""
        return self._aw_api().open_od_for_client(client, hint_path)

    # ── Pin folder (Find/Change) ─────────────────────────────────────
    # Delegated to audit_web.Api so the year-scope filter (current
    # year / older / fire-jobs / all) and the matching logic stay
    # single-sourced. User asked the IUQ pin picker to support the
    # same scopes as the audit Find Folder dialog — instead of forking
    # the scorer here we just call through.
    def _aw_api(self):
        import audit_web as _aw
        if not hasattr(self, "_aw_singleton"):
            self._aw_singleton = _aw.Api()
            try: self._aw_singleton.attach(self._window)
            except Exception: pass
        return self._aw_singleton

    def list_year_folders(self) -> dict:
        try:
            return self._aw_api().list_year_folders()
        except Exception as ex:
            return {"ok": False, "error": str(ex), "folders": []}

    def list_subfolders(self, path: str) -> dict:
        try:
            return self._aw_api().list_subfolders(path)
        except Exception as ex:
            return {"ok": False, "error": str(ex), "subfolders": []}

    # Per-client memory items (mirror Tk's shared right-click menu)
    def get_search_aliases(self, client):
        return self._aw_api().get_search_aliases(client)
    def set_search_aliases(self, client, aliases):
        return self._aw_api().set_search_aliases(client, aliases)
    def list_property_groups(self):
        return self._aw_api().list_property_groups()
    def find_property_for_folder(self, folder_basename):
        return self._aw_api().find_property_for_folder(folder_basename)
    def add_folder_to_property_group(self, group_name, folder_basename):
        return self._aw_api().add_folder_to_property_group(group_name, folder_basename)
    def remove_folder_from_property_group(self, group_name, folder_basename):
        return self._aw_api().remove_folder_from_property_group(group_name, folder_basename)
    def create_property_group(self, group_name, folder_basename=""):
        return self._aw_api().create_property_group(group_name, folder_basename)
    def clear_folder_path(self, client):
        return self._aw_api().clear_folder_path(client)
    def reset_client_memory(self, client):
        return self._aw_api().reset_client_memory(client)
    def set_commercial(self, client, on):
        return self._aw_api().set_commercial(client, on)
    def reaudit_one(self, client):
        return self._aw_api().reaudit_one(client)
    # SharePoint import passthroughs (user wants to import from SP
    # straight from the IUQ audit subview, same flow as the audit
    # panel's per-row 📥 Import from SharePoint…).
    def sp_find_matches(self, client, unit=""):
        return self._aw_api().sp_find_matches(client, unit)
    def property_structure(self, client):
        return self._aw_api().property_structure(client)
    def set_property_settings(self, client, is_commercial=None, aliases=None):
        return self._aw_api().set_property_settings(client, is_commercial, aliases)
    def list_day_units(self, client):
        return self._aw_api().list_day_units(client)
    def set_day_units(self, client, paths):
        return self._aw_api().set_day_units(client, paths)
    def sp_copy_to_pics(self, client, sp_path, target_pics, job_path):
        return self._aw_api().sp_copy_to_pics(client, sp_path, target_pics, job_path)
    def sp_pin_folder(self, client, sp_path):
        return self._aw_api().sp_pin_folder(client, sp_path)
    def sp_mark_in_od(self, client, sp_path):
        return self._aw_api().sp_mark_in_od(client, sp_path)
    def sp_force_pull(self, sp_path):
        return self._aw_api().sp_force_pull(sp_path)
    def sp_cloud_only_count(self, sp_path):
        return self._aw_api().sp_cloud_only_count(sp_path)
    def sp_browse_for_folder(self):
        return self._aw_api().sp_browse_for_folder()
    def sp_reject_match(self, client, sp_path):
        return self._aw_api().sp_reject_match(client, sp_path)
    def sp_open_folder(self, sp_path):
        return self._aw_api().sp_open_folder(sp_path)
    def open_rundoc_for_sp_match(self, sp_path):
        return self._aw_api().open_rundoc_for_sp_match(sp_path)
    def open_folder(self, path):
        return self._aw_api().open_folder(path)
    # 📋 Copy PICS to clipboard (XA upload helper)
    def list_pics_stages(self, client):
        return self._aw_api().list_pics_stages(client)
    def copy_pics_to_clipboard(self, client, stage=""):
        return self._aw_api().copy_pics_to_clipboard(client, stage)
    # 📎 Trello attachments manager
    def list_card_attachments(self, card_id):
        return self._aw_api().list_card_attachments(card_id)
    def download_card_attachments(self, card_id, attachment_ids, client=""):
        return self._aw_api().download_card_attachments(card_id, attachment_ids, client)
    def fetch_trello_image(self, url):
        return self._aw_api().fetch_trello_image(url)

    def list_folder_candidates(self, client: str, year: str = "") -> dict:
        """Year-scoped folder candidates. `year` accepts "" (current),
        "all", "fire", a 4-digit year, or a full top-level folder name.
        Mirrors audit_web.list_folder_candidates byte-for-byte by
        delegation — see that method for the full scope semantics."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            return self._aw_api().list_folder_candidates(client, year or "")
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def pin_folder(self, client: str, path: str) -> dict:
        """Persist an OD folder pin for an IUQ client. Mirrors the
        audit's set_folder_path — keys + storage are shared so audit
        / snapshot / IUQ all see the same pinned folder."""
        if not client or not path:
            return {"ok": False, "error": "client + path required"}
        if not os.path.isdir(path):
            return {"ok": False, "error": "folder doesn't exist"}
        try:
            # Scaffold EMS/PICS/DOCS so future operations land in
            # canonical subfolders. Idempotent — no-op when they exist.
            for sub in ("EMS", os.path.join("EMS", "DOCS"),
                        os.path.join("EMS", "PICS")):
                cand = os.path.join(path, sub)
                if not os.path.isdir(cand):
                    try: os.makedirs(cand, exist_ok=True)
                    except OSError: pass
            persistence.set_folder_path(client, path)
            return {"ok": True, "path": path}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def clear_folder_pin(self, client: str) -> dict:
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            persistence.set_folder_path(client, "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_pinned_folder(self, client: str) -> str:
        if not client: return ""
        try:
            return persistence.get_folder_path(client) or ""
        except Exception:
            return ""

    def make_folders(self, client):
        """Scaffold EMS / EMS/DOCS / EMS/PICS under the client's
        resolved folder. Mirrors the Tk IUQ's 📂 Make folders.

        Resolution order (no Tk dependency):
          1. Persistence pin (from any Find/Change Folder action)
          2. Auto-resolve via the audit folder lookup (same year-walk
             audit_logic does — pulls the same canonical folder the
             audit row resolved to)
          3. Error with actionable next step (Find Folder in audit)
        """
        if not client: return {"ok": False, "error": "no client"}
        import os as _os
        p = ""
        try:
            p = persistence.get_folder_path(client) or ""
        except Exception:
            p = ""
        # Auto-resolve when nothing pinned — same logic the audit
        # uses, so IUQ + audit always agree on which folder is "the"
        # folder for this client.
        if not p:
            try:
                import audit_logic as _al
                import paths
                import datetime as _dt
                results, _err = _al.audit_jobs(
                    [client], paths.audit_base(),
                    run_date=_dt.date.today(),
                    use_cache=True) or ([], None)
                if results and results[0].get("found"):
                    p = results[0].get("path") or ""
                    # Persist what we just resolved so subsequent
                    # actions don't re-walk the year folder.
                    if p:
                        try: persistence.set_folder_path(client, p)
                        except Exception: pass
            except Exception:
                pass
        if not p:
            return {"ok": False,
                    "error": f"Couldn't find a folder for {client}. "
                             "Open the audit panel → right-click the row → "
                             "🔎 Find folder to pin one."}
        if not _os.path.isdir(p):
            return {"ok": False, "error": f"Folder doesn't exist: {p}"}
        try:
            _os.makedirs(_os.path.join(p, "EMS", "DOCS"), exist_ok=True)
            _os.makedirs(_os.path.join(p, "EMS", "PICS"), exist_ok=True)
            return {"ok": True, "path": p}
        except OSError as ex:
            return {"ok": False, "error": str(ex)}

    def fetch_card_checklists(self, card_id: str) -> dict:
        """On-demand checklist fetch for a specific Trello card. Used
        when the IUQ row was synthesized from APA (no checklist scan)
        or when the card was pinned after the last refresh — without
        this the detail view shows 'No checklist on card' even when
        the card has them on Trello.

        Pulls the card via `trello_client.get_card(card_id)` and runs
        it through the same `TRACKED_CHECKLISTS` extractor the
        bulk-scan path uses, so output shape matches `_shape_row`."""
        if not card_id:
            return {"ok": False, "error": "no card_id"}
        try:
            import trello_client as tc
            card = tc.get_card(card_id) or {}
            if not card:
                return {"ok": False, "error": "Trello card not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        try:
            checklists = []
            for cl_name, expected in iuq.TRACKED_CHECKLISTS:
                cl = iuq._find_checklist(card, cl_name)
                items_by_name = iuq._items_dict(cl) if cl else {}
                items = []
                for item_name in expected:
                    it = items_by_name.get(item_name)
                    if it:
                        items.append({
                            "id":    it.get("id", ""),
                            "name":  item_name,
                            "done":  (it.get("state") or "").lower() == "complete",
                            "state": (it.get("state") or "").lower(),
                        })
                    else:
                        items.append({"id": "", "name": item_name,
                                       "done": False, "state": "missing"})
                checklists.append({
                    "name":    cl_name,
                    "id":      (cl.get("id") or "") if cl else "",
                    "present": cl is not None,
                    "items":   items,
                })
            # Also pull any OTHER checklists on the card so the user
            # sees the truth — sometimes the card has "Initial Admin"
            # (no hyphen) or a custom-named one the tracked list
            # doesn't include. Show those too with a different style.
            tracked_lower = {n.lower() for n, _ in iuq.TRACKED_CHECKLISTS}
            for cl in card.get("checklists") or []:
                nm = (cl.get("name") or "").strip()
                if not nm or nm.lower() in tracked_lower:
                    continue
                items = []
                for it in (cl.get("checkItems") or []):
                    items.append({
                        "id":    it.get("id", ""),
                        "name":  it.get("name") or "",
                        "done":  (it.get("state") or "").lower() == "complete",
                        "state": (it.get("state") or "").lower(),
                    })
                checklists.append({
                    "name":    nm,
                    "id":      cl.get("id") or "",
                    "present": True,
                    "items":   items,
                    "extra":   True,
                })
            pooled = [it for cl in checklists for it in (cl["items"] or [])]
            done = sum(1 for it in pooled if it["done"])
            return {"ok": True, "checklists": checklists,
                    "done": done, "total": len(pooled),
                    "card_name": card.get("name") or ""}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def search_trello(self, query):
        if not query or len(query.strip()) < 2: return []
        try:
            import trello_client as tc
            return [{
                "card_id":  h.get("card_id") or h.get("id") or "",
                "name":     h.get("name") or "",
                "board":    h.get("board") or h.get("board_name") or "",
                "lane":     h.get("list_name") or h.get("lane") or "",
                "short_url": h.get("url") or h.get("shortUrl") or "",
            } for h in (tc.find_cards_by_name(query.strip()) or [])[:20]]
        except Exception:
            return []

    def request_docusketch(self, client, card_id: str = ""):
        """Post the canonical Docusketch request comment on the
        client's Trello card. Resolution chain via card_resolver."""
        import card_resolver as _cr
        cid, err = _cr.resolve(client, card_id)
        if not cid:
            return {"ok": False, "error": err}
        try:
            import docusketch_requests as dr
            entry = dr.request(cid, client_name=client)
            if entry is None:
                return {"ok": False,
                        "error": f"Trello lookup failed for card {cid} (archived or no access)"}
            return {"ok": True, "card_id": cid,
                    "posted": bool(entry.get("comment_posted", True))}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def create_trello_card_for(self, client: str, name: str = "") -> dict:
        """Create a Trello card in the Initial Inspections lane for a
        client that doesn't have one yet (manual IUQ row or APA-
        synthesized row). Mirrors Tk initial_upload_queue.py:3066
        _create_trello_card_for: creates the card, pins it to the
        client, returns the new card_id + shortUrl.

        Returns {ok, card_id, short_url, name, lane}.
        """
        if not client or not client.strip():
            return {"ok": False, "error": "client required"}
        client = client.strip()
        # Use the explicit `name` if the manual-row dialog captured a
        # fuller title, else fall back to plain client name.
        card_name = (name or "").strip() or client
        try:
            import trello_client as tc
            from initial_upload_queue import (
                LIST_ID_INITIAL_INSPECTIONS,
                LANE_LABEL_BY_LIST_ID)
            created = tc.create_card(LIST_ID_INITIAL_INSPECTIONS, card_name)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        if not created:
            return {"ok": False, "error": "Trello API rejected the create"}
        cid = (created.get("id") or "").strip()
        short = (created.get("shortUrl") or "").strip()
        # Pin the new card to the client so audit/snapshot find it.
        try:
            persistence.set_trello_card_id(client, cid)
        except Exception:
            pass
        # Drop the matching manual entry if one was on file — the row
        # now has a real Trello card, no longer "manual-only".
        try:
            persistence.remove_manual_iuq_card(client)
        except Exception:
            pass
        # Force a re-render on the next refresh by invalidating cache.
        try: self._last_rows = []
        except Exception: pass
        return {"ok": True, "card_id": cid, "short_url": short,
                "name": card_name,
                "lane": LANE_LABEL_BY_LIST_ID.get(
                    LIST_ID_INITIAL_INSPECTIONS, "Initial Insp.")}

    def pin_trello(self, client, card_id):
        if not client or not card_id:
            return {"ok": False}
        try:
            persistence.set_trello_card_id(client, card_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def scan_downloads_for_card(self, client):
        """Mirror audit_web.scan_downloads but called from IUQ."""
        try:
            import audit_web as _aw
            return _aw.Api().scan_downloads(client)
        except Exception:
            return {"downloads": "", "client": client, "candidates": []}

    def do_import(self, client, kind, zip_paths, dest_subfolder=""):
        """Route through the audit_web importer — same backend, same
        per-extension routing + activity-aware PICS subfolder. The
        optional `dest_subfolder` is the user-picked PICS stage folder."""
        try:
            import audit_web as _aw
            return _aw.Api().do_import(client, kind, zip_paths, dest_subfolder)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def stamp_photo_dates(self, folder, date_iso):
        try:
            import audit_web as _aw
            return _aw.Api().stamp_photo_dates(folder, date_iso)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def request_docusign(self, client):
        try:
            import audit_web as _aw
            return _aw.Api().request_docusign(client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_card(self, url):
        if not url: return False
        try: webbrowser.open(url); return True
        except Exception: return False

    # ── P0: Per-item checklist toggle ────────────────────────────────
    def toggle_check_item(self, card_id, check_item_id, complete):
        """Mark a Trello checklist item complete/incomplete. Backend
        write — picks up next refresh."""
        if not card_id or not check_item_id:
            return {"ok": False, "error": "missing ids"}
        try:
            import trello_client as tc
            state = "complete" if complete else "incomplete"
            tc.set_check_item_state(card_id, check_item_id, state)
            # Refresh the cached row's progress so the UI reflects the change
            for r in self._last_rows:
                if r.get("card_id") == card_id:
                    for it in (r.get("items") or []):
                        if it.get("id") == check_item_id:
                            it["done"] = bool(complete)
                            break
                    r["done"] = sum(1 for x in r.get("items") or [] if x.get("done"))
                    r["progress"] = f"{r['done']}/{r['total']}" if r.get("items") else "—"
                    break
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P0: Canned comments ─────────────────────────────────────────
    # Canonical phrases from the Tk IUQ right-click menu (per memory:
    # project_trello_completion_phrases). Posting these on the Trello
    # card mirrors the Tk panel's canned-comment flow.
    CANNED_COMMENTS = {
        "ipr":    "Initial Photo Report Created and Uploaded to OD.",
        "upload": "Initial Upload submitted To WC.",
    }

    def post_canned(self, card_id, key):
        """Post a canonical canned comment by key."""
        if not card_id:
            return {"ok": False, "error": "no card"}
        text = self.CANNED_COMMENTS.get(key, "")
        if not text:
            return {"ok": False, "error": f"unknown phrase: {key}"}
        try:
            import trello_client as tc
            tc.post_comment(card_id, text)
            return {"ok": True, "text": text}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P0: Manual add row ──────────────────────────────────────────
    # IMPORTANT: must use persistence.add_manual_iuq_card (the same
    # helper Tk's _open_add_manual_dialog uses) — that's the single
    # store iuq._fetch_queue_from_trello reads from when merging
    # manual rows into the queue. Previously this wrote to a
    # different key ("iuq_manual_rows") that the queue never read,
    # so manual adds appeared to succeed but never showed up.
    def add_manual_row(self, client, trello_url=""):
        """Add a manual IUQ row that persists across sessions. Mirrors
        the Tk ➕ Add manual dialog (initial_upload_queue.py:3329).
        trello_url is optional — when present, the card_id is parsed
        so comments/autotick still fire for the row."""
        if not client or not client.strip():
            return {"ok": False, "error": "client required"}
        try:
            import re as _re
            url = (trello_url or "").strip()
            m = _re.search(r"trello\.com/c/([A-Za-z0-9]+)", url) if url else None
            card_id = m.group(1) if m else ""
            persistence.add_manual_iuq_card(
                client.strip(), card_url=url, card_id=card_id)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        # Invalidate any cached row list so the next refresh re-merges
        # manual entries in.
        try: self._last_rows = []
        except Exception: pass
        # Return the SHAPED row so the frontend can show it immediately —
        # the row no longer depends on a successful (and possibly slow /
        # offline) background Trello re-fetch to appear in the queue.
        try:
            row = _shape_row({
                "card_id":    card_id,
                "shortUrl":   url,
                "name":       client.strip(),
                "client":     client.strip(),
                "lane":       "Manual",
                "list_id":    "",
                "board_id":   "",
                "labels":     [],
                "checklists": [],
                "done":       False,
                "manual":     True,
            })
        except Exception:
            row = None
        return {"ok": True, "card_id": card_id, "row": row}

    def remove_manual_row(self, client):
        if not client: return {"ok": False}
        try:
            persistence.remove_manual_iuq_card(client)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def list_manual_rows(self):
        try:
            return persistence.get_manual_iuq_cards() or []
        except Exception:
            return []

    # ── P1: Flag missing for IUQ row ────────────────────────────────
    def flag_missing(self, card_id, client, item_text, note=""):
        """Record a missing item for an IUQ card + post Trello comment.
        Mirrors the audit's flag_missing but stage='intake' since
        IUQ is the intake surface. Uses `missing_items_tracker`."""
        if not client or not item_text:
            return {"ok": False, "error": "client + item required"}
        try:
            import missing_items_tracker as _mit
            _mit.capture_missing_items(
                client_name=client,
                items=[item_text],
                stage="intake",
                note=note,
                card_id=card_id or "")
        except Exception:
            pass
        posted = False
        if card_id:
            try:
                import trello_client as tc
                body = f"🚩 **Flagged missing at intake**: {item_text}"
                if note: body += f"\n\n{note}"
                tc.post_comment(card_id, body)
                posted = True
            except Exception:
                pass
        return {"ok": True, "posted_trello": posted}

    # ── P1: Per-card notes ──────────────────────────────────────────
    def get_card_note(self, card_id):
        if not card_id: return ""
        try:
            notes = persistence.get("iuq_card_notes") or {}
            return notes.get(card_id, "") if isinstance(notes, dict) else ""
        except Exception:
            return ""

    def set_card_note(self, card_id, text):
        if not card_id:
            return {"ok": False}
        try:
            notes = persistence.get("iuq_card_notes") or {}
            if not isinstance(notes, dict): notes = {}
            notes[card_id] = (text or "").strip()
            persistence.set_value("iuq_card_notes", notes)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def _emit_done(self, *, ok, error=""):
        import json
        payload = {"ok": ok, "rows": self._last_rows if ok else [],
                   "lanes": _lanes(), "error": error}
        js = json.dumps(payload, default=str)
        if not self._window:
            return
        # Event listeners live on the iframe's window, NOT the home
        # shell's. Without the iframe forwarding the `iuq:done`
        # event fires in the wrong context and the UI sits in the
        # loading state forever. Same fix as audit_web._emit.
        raw = (f"window.dispatchEvent(new CustomEvent('iuq:done', "
               f"{{detail: {js}}}));")
        iframe = raw.replace("window.dispatchEvent(",
                             "__ems_iframe_win__.dispatchEvent(")
        wrapped = (
            "(function(){"
            "try{" + raw + "}catch(e){}"
            "try{"
            "var __f=document.getElementById('content-frame');"
            "if(__f && __f.contentWindow){"
            "var __ems_iframe_win__=__f.contentWindow;"
            + iframe +
            "}"
            "}catch(e){}"
            "})();"
        )
        try:
            self._window.evaluate_js(wrapped)
        except Exception:
            pass


def _lanes():
    return list(iuq.LANE_LABEL_BY_LIST_ID.values())


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Initial Upload Queue — EMS Tools (web)",
        url=INDEX_HTML, js_api=api,
        width=1280, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
