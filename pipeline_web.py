"""Pipeline — Pywebview panel.

Renders every job lifecycle row (from `ems_db.job_lifecycle`) with
stage filter chips + search + sync button. Per-stage classification
via `pipeline_stages.derive_stage`. Per-row timeline modal pulls
`ems_db.list_transitions`. Export to per-stage Excel sheets.

Launch:
    python pipeline_web.py
    # or via launcher:
    python launcher.py --tool pipeline_web
"""
from __future__ import annotations

import datetime as _dt
from concurrent.futures import ThreadPoolExecutor
import os
import sys
import time
import webbrowser
from typing import Any

import webview

# Make sure the EMS Automation scripts dir is on sys.path. When this
# file runs standalone (double-clicked / from cmd) the cwd may be
# elsewhere; this anchors imports to the same dir as launcher.py.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import ems_db
import pipeline_stages as ps
import pipeline_store
from web_helpers import run_bg as _wh_run_bg


ASSETS_DIR = os.path.join(_HERE, "pipeline_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


def _row_to_jsdict(r: dict) -> dict:
    """Shape one lifecycle row for the frontend. Pre-computes the
    cheap derivations (days_in_stage, days_since_created, anomaly
    flag) here so the JS side stays declarative."""
    days_in = ps.days_in_stage(r)
    days_age = ps.days_since_created(r)
    stage = r.get("current_stage") or ""
    thresholds = ps.get_thresholds()
    threshold = thresholds.get(stage, 9999)
    stall = "none"
    if days_in > threshold * 2:
        stall = "bad"
    elif days_in > threshold:
        stall = "warn"
    # Anomaly check — defaults guard already inside is_anomaly.
    try:
        is_anomaly = ps.is_anomaly(r)
    except Exception:
        is_anomaly = False
    return {
        "card_id":        r.get("card_id") or "",
        "client":         r.get("client_display") or "",
        "stage":          stage,
        "stage_label":    ps.STAGE_LABELS.get(stage, stage),
        "days_in_stage":  days_in,
        "age":            days_age,
        "last_activity":  (r.get("last_activity_at") or "")[:10],
        "owner":          r.get("owner") or "",
        "board":          r.get("board_name") or "",
        "lane":           r.get("list_name") or "",
        "card_url":       r.get("card_url") or "",
        "stall":          stall,
        "threshold":      threshold,
        "is_anomaly":     is_anomaly,
    }


# ── 🗂 Board view (live Trello kanban) ───────────────────────────────
# Boards the kanban mirrors, in display order. key = frontend section id;
# name must match the Trello board name (case-insensitive).
BOARD_SPECS = (
    ("wip", "WORK IN PROGRESS"),
    ("est", "ESTIMATING"),
    ("contents", "CONTENTS"),
)

# Lanes never shown on the board — spacers + admin/template columns that
# aren't real jobs. (Per-CARD noise is handled by pipeline_stages.
# is_pipeline_skip.)
_NOISE_LANE_SUBSTRINGS = (
    "spacer", "template", "templet", "marketing team",
    "on call", "on-call", "collections process", "disposal",
    "garments", "labels",
)

# Days-in-lane stall thresholds for the board chip — a cheap, lane-
# agnostic proxy off last activity. (The Stages table keeps the precise
# per-stage thresholds.)
_BOARD_STALL_WARN = 7
_BOARD_STALL_BAD = 14


def _is_noise_lane(lane_name):
    low = (lane_name or "").strip().lower()
    if not low:
        return True
    return any(s in low for s in _NOISE_LANE_SUBSTRINGS)


def _days_since_iso(iso):
    """Whole days between an ISO date/datetime string and today; 0 on
    parse failure."""
    if not iso:
        return 0
    try:
        d = _dt.date.fromisoformat(str(iso)[:10])
        return max(0, (_dt.date.today() - d).days)
    except Exception:
        return 0


_CARD_FIELDS = ("name,desc,shortUrl,idBoard,idList,labels,due,"
                "dueComplete,dateLastActivity,closed")


def _build_board(tc, ps, key, bname, board_obj):
    """Pull + shape ONE Trello board into its lanes/cards payload.
    Shared by board_view (both boards) and board_view_one (single-board
    refresh). `board_obj` is the raw board dict from list_boards (or None
    when the board name isn't found)."""
    if not board_obj:
        return {"key": key, "name": bname, "board_id": "",
                "lanes": [], "missing": True}
    bid = board_obj.get("id")
    try:
        lists = tc._call(f"/boards/{bid}/lists",
                         params={"fields": "name", "filter": "open"}) or []
    except Exception:
        lists = []
    # One board-level card request replaces one request per lane. Large WIP
    # boards previously needed dozens of serial round trips before the first
    # paint. Trello can inline every checklist in the same response.
    cards_by_list = None
    try:
        raw_cards = tc._call(f"/boards/{bid}/cards", params={
            "fields": _CARD_FIELDS, "filter": "open", "checklists": "all",
            "checklist_fields": "name,pos",
        }) or []
        cards_by_list = {}
        for card in raw_cards:
            if card.get("closed"):
                continue
            try:
                card = tc.order_checklists(card)
            except Exception:
                pass
            cards_by_list.setdefault(card.get("idList"), []).append(card)
    except Exception:
        cards_by_list = None
    lanes = []
    for l in lists:
        lname = (l.get("name") or "").strip()
        if _is_noise_lane(lname):
            continue
        if cards_by_list is not None:
            cards = cards_by_list.get(l.get("id"), [])
        else:
            try:
                cards = tc.cards_in_list_with_checklists(
                    l.get("id"), fields=_CARD_FIELDS)
            except Exception:
                cards = []
        shaped = []
        for c in cards:
            try:
                if ps.is_pipeline_skip(c.get("name") or "", lname):
                    continue
            except Exception:
                pass
            shaped.append(_card_to_board_dict(c, lname))
        lanes.append({"list_id": l.get("id"), "name": lname,
                      "count": len(shaped), "cards": shaped})
    return {"key": key, "name": board_obj.get("name") or bname,
            "board_id": bid, "lanes": lanes}


def _card_to_board_dict(card, lane_name):
    """Shape one Trello card for the board UI: client name + loss-type
    chips + checklist progress + due/overdue + days-in-lane stall.
    JSON-only primitives."""
    import trello_client as tc
    name = (card.get("name") or "").strip()
    days = _days_since_iso(card.get("dateLastActivity"))
    stall = "bad" if days > _BOARD_STALL_BAD else (
        "warn" if days > _BOARD_STALL_WARN else "none")
    try:
        done, total = tc.checklist_progress(card)
    except Exception:
        done, total = 0, 0
    try:
        loss = tc.card_loss_type(card)
    except Exception:
        loss = ""
    due = card.get("due") or ""
    due_complete = bool(card.get("dueComplete"))
    overdue = False
    if due and not due_complete:
        try:
            overdue = _dt.date.fromisoformat(str(due)[:10]) < _dt.date.today()
        except Exception:
            overdue = False
    return {
        "card_id":      card.get("id") or "",
        "name":         name,
        "client":       name,
        "url":          card.get("shortUrl") or "",
        "list_id":      card.get("idList") or "",
        "lane":         lane_name,
        "loss_types":   [s.strip() for s in
                         (loss.split(",") if loss else []) if s.strip()],
        "checklist":    {"done": done, "total": total},
        "due":          str(due)[:10] if due else "",
        "due_complete": due_complete,
        "overdue":      overdue,
        "days_in_lane": days,
        "stall":        stall,
        "last_activity_at": card.get("dateLastActivity") or "",
    }


def _trello_board_payload():
    """Pull all configured transition boards from the Trello adapter."""
    import trello_client as tc
    try:
        boards_by_name = {
            (b.get("name") or "").strip().upper(): b
            for b in (tc.list_boards() or [])}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "boards": []}
    with ThreadPoolExecutor(max_workers=len(BOARD_SPECS),
                            thread_name_prefix="trello-board") as pool:
        futures = [pool.submit(_build_board, tc, ps, key, bname,
                               boards_by_name.get(bname.strip().upper()))
                   for key, bname in BOARD_SPECS]
        out = [future.result() for future in futures]
    return {"ok": True, "boards": out, "source": "trello"}


class Api:
    """Methods exposed to JS via `pywebview.api`.

    Every call is async on the JS side; pywebview marshals across the
    process boundary automatically. Long-running operations (sync,
    enrichment) are spawned on background threads so the WebView UI
    stays responsive.
    """

    def __init__(self):
        self._window = None
        self._last_rows = []
        self._sync_running = False
        self._audit = None  # lazily-built audit_web.Api for card audits
        self._audit_card_cache = {}
        self._division_reconcile_cache = {}
        self._document_cache = {}
        self._board_view_cache = None
        self._workspace_cache = {}

    def _workspace_cache_key(self, client: str, card_id: str = "",
                             division: str = ""):
        return ((client or "").strip().casefold(),
                (card_id or "").strip().casefold(),
                (division or "EMS").strip().upper())

    def _invalidate_workspace(self, client: str = "", card_id: str = ""):
        client_key = (client or "").strip().casefold()
        card_key = (card_id or "").strip().casefold()
        for key in list(self._workspace_cache):
            if ((client_key and key[0] == client_key) or
                    (card_key and key[1] == card_key) or
                    (not client_key and not card_key)):
                self._workspace_cache.pop(key, None)

    def personal_preferences(self) -> dict:
        """Safe presentation-only choices for this Windows user."""
        import config
        cfg = config.load() or {}
        return {
            "density": (cfg.get("ui_density") or "comfortable"),
            "default_view": (cfg.get("pipeline_default_view") or "board"),
            "reduce_motion": bool(cfg.get("reduce_motion", False)),
        }

    # ── 🗂 Board view + drag-move + per-card audit actions ───────────
    def board_view(self, force_trello: bool = False) -> dict:
        """Load the Linguar-owned shared Pipeline first.

        Trello is now an adapter: it seeds an empty Pipeline and refreshes it
        only when requested.  Missing migration 011 fails soft to the legacy
        live-Trello behaviour so an employee is never locked out by rollout.
        """
        if not force_trello and self._board_view_cache:
            cached_at, cached_payload = self._board_view_cache
            if time.monotonic() - cached_at < 30:
                return {**cached_payload, "cached": True}
        if not force_trello:
            saved = pipeline_store.load_board_cache()
            if saved.get("ok") and saved.get("boards"):
                self._board_view_cache = (time.monotonic(), saved)
                return saved
            shared = pipeline_store.load_boards(BOARD_SPECS)
            if shared.get("ok") and shared.get("boards"):
                self._board_view_cache = (time.monotonic(), shared)
                return shared
        live = _trello_board_payload()
        if not live.get("ok"):
            shared = pipeline_store.load_boards(BOARD_SPECS)
            if shared.get("ok"):
                shared["warning"] = "Trello unavailable; showing shared Pipeline"
                self._board_view_cache = (time.monotonic(), shared)
                return shared
            return live
        live.setdefault("source", "trello")
        mirrored = pipeline_store.mirror_boards(live)
        live["mirrored"] = bool(mirrored.get("ok"))
        live["schema_missing"] = bool(mirrored.get("schema_missing"))
        pipeline_store.save_board_cache(live)
        self._board_view_cache = (time.monotonic(), live)
        return live

    def board_view_shared_refresh(self) -> dict:
        """Refresh the saved projection after the UI has already painted."""
        shared = pipeline_store.load_boards(BOARD_SPECS)
        if shared.get("ok") and shared.get("boards"):
            self._board_view_cache = (time.monotonic(), shared)
            return shared
        # Until the shared Pipeline migration is installed, keep the instant
        # disk-cache paint but refresh that projection from Trello in the
        # background.  This avoids leaving users on a stale board indefinitely.
        return self.board_view(force_trello=True)

    def board_view_one(self, key: str) -> dict:
        """Re-pull a SINGLE board (the per-board ↻ refresh) so the user
        can refresh one division board without waiting on all three."""
        spec = next((s for s in BOARD_SPECS if s[0] == key), None)
        if not spec:
            return {"ok": False, "error": f"unknown board '{key}'"}
        import trello_client as tc
        import pipeline_stages as ps
        try:
            boards_by_name = {
                (b.get("name") or "").strip().upper(): b
                for b in (tc.list_boards() or [])}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        bname = spec[1]
        board = _build_board(tc, ps, key, bname,
                             boards_by_name.get(bname.strip().upper()))
        mirrored = pipeline_store.mirror_boards({"boards": [board]})
        return {"ok": True, "board": board, "source": "trello",
                "mirrored": bool(mirrored.get("ok"))}

    def move_card(self, card_id: str, list_id: str) -> dict:
        """Move a card to another lane on the REAL Trello board. The
        frontend confirms before calling this (drag-to-move with a
        'Move X to <lane>?' prompt)."""
        if not card_id or not list_id:
            return {"ok": False, "error": "card_id + list_id required"}
        shared = pipeline_store.move_card(card_id, list_id)
        self._board_view_cache = None
        self._invalidate_workspace(card_id=card_id)
        try:
            import trello_client as tc
            ok = tc.move_card(card_id, list_id)
            pipeline_store.mark_card_sync(
                card_id, ok=bool(ok),
                error="Trello rejected the move" if not ok else "")
            if ok:
                return {"ok": True, "synced": True,
                        "stored": bool(shared.get("ok"))}
            if shared.get("ok"):
                return {"ok": True, "synced": False,
                        "warning": "Saved in Linguar Hub; Trello needs review"}
            return {"ok": False, "error": "Trello rejected the move"}
        except Exception as ex:
            pipeline_store.mark_card_sync(card_id, ok=False, error=str(ex))
            if shared.get("ok"):
                return {"ok": True, "synced": False,
                        "warning": "Saved in Linguar Hub; Trello is unavailable"}
            return {"ok": False, "error": str(ex)}

    def _audit_api(self):
        if self._audit is None:
            import audit_web
            self._audit = audit_web.Api()
        return self._audit

    def audit_card(self, client: str) -> dict:
        """Run the single-job audit for this card's client and return a
        compact pass/fail summary for the card popover. Delegates to
        audit_web — same engine the Audit panel uses."""
        if not client:
            return {"ok": False, "error": "client required"}
        cache_key = client.strip().casefold()
        cached = self._audit_card_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 90:
            return dict(cached[1])
        try:
            res = self._audit_api().audit_one_job(client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not res or res.get("ok") is False:
            return {"ok": False,
                    "error": (res or {}).get("error") or "audit failed"}
        row = res.get("row") or {}
        shaped = {
            "ok":            True,
            "client":        res.get("canonical") or client,
            "found":         bool(row.get("found")),
            "flagged":       bool(row.get("flagged")),
            "form_issues":   list(row.get("form_issues") or []),
            "photo_issues":  list(row.get("photo_issues") or []),
            "requirements":  [r.get("label") for r
                              in (row.get("requirements") or [])],
            "aging":         int(row.get("aging") or 0),
            "activity":      list(row.get("activity") or []),
            "techs":         list(row.get("techs") or []),
            "carrier":       row.get("carrier") or "",
            "folder":        row.get("folder") or "",
            "path":          row.get("path") or "",
            "last_seen":     row.get("last_seen") or "",
            "misplaced_forms": list(row.get("misplaced_forms") or []),
            "misplaced_photos": list(row.get("misplaced_photos") or []),
            "trello_card_id": row.get("trello_card_id") or "",
        }
        self._audit_card_cache[cache_key] = (time.monotonic(), shaped)
        return shaped

    def job_card_workspace(self, client: str, card_id: str = "",
                           division: str = "") -> dict:
        """Full Pipeline card: audit + CRM + Trello transition material."""
        started = time.monotonic()
        workspace_key = self._workspace_cache_key(client, card_id, division)
        cached_workspace = self._workspace_cache.get(workspace_key)
        if cached_workspace and time.monotonic() - cached_workspace[0] < 45:
            return {**cached_workspace[1], "cached": True,
                    "load_ms": round((time.monotonic() - started) * 1000)}
        audit_api = self._audit_api()
        reconcile_divisions = getattr(
            audit_api, "reconcile_crm_division_trello_cards", None)
        reconcile_key = client.strip().casefold()

        def load_division_reconciliation():
            cached = self._division_reconcile_cache.get(reconcile_key)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
            result = (reconcile_divisions(client) if reconcile_divisions else
                      {"ok": True, "divisions": [], "has_conflict": False})
            self._division_reconcile_cache[reconcile_key] = (
                time.monotonic(), result)
            return result

        # Card reconciliation searches Trello and is independent of the
        # folder audit. Start it first so its network time overlaps the audit
        # and CRM reads instead of adding ~5 seconds after them.
        reconcile_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="division-reconcile")
        reconcile_future = reconcile_pool.submit(load_division_reconciliation)
        summary = self.audit_card(client)
        if not summary.get("ok"):
            reconcile_pool.shutdown(wait=False, cancel_futures=True)
            return summary
        crm = audit_api.crm_job_workspace(client, summary)
        try:
            division_reconciliation = reconcile_future.result()
        finally:
            reconcile_pool.shutdown(wait=False)
        # crm_job_workspace already fetched these pins. Re-reading them here
        # used to add another shared-database round trip to every open.
        division_trello_cards = {
            "ok": True, "cards": list(crm.get("division_trello_cards") or [])}
        if not division_trello_cards["cards"]:
            division_trello_cards = audit_api.crm_division_trello_cards(client)
        division_cards = division_trello_cards.get("cards", [])
        info_sections, checklists, comments, attachments, members = [], [], [], [], []
        try:
            import ems_db
            import job_settings
            job = ems_db.find_job_by_name(client) or {}
            values = job_settings.stored_values(job)
            grouped = {}
            order = []
            for fid, section, _key, label, _core in job_settings.FIELDS:
                value = str(values.get(fid) or "").strip()
                if not value:
                    continue
                if section not in grouped:
                    grouped[section] = []
                    order.append(section)
                grouped[section].append({"id": fid, "label": label, "value": value})
            info_sections = [{"name": section.title(), "fields": grouped[section]}
                             for section in order]
        except Exception:
            pass
        from ems_db_common import normalize_division
        requested_division = normalize_division(division) if division else ""
        opened_id = (card_id or "").strip()
        if not requested_division and opened_id:
            requested_division = next((
                str(card.get("division") or "") for card in division_cards
                if str(card.get("card_id") or "").casefold() == opened_id.casefold()
            ), "")
        selected_division = requested_division or "EMS"
        selected_card = next((card for card in division_cards
                              if card.get("division") == selected_division), {})
        cid = str(selected_card.get("card_id") or "").strip()
        # A just-opened legacy card can predate the shared pin. It remains
        # the EMS card until the user explicitly assigns another division.
        if not cid and selected_division == "EMS":
            cid = opened_id or (summary.get("trello_card_id") or "").strip()
        # Linguar Hub is the durable source. Trello below is now an import/
        # compatibility adapter and refreshes this local copy when available.
        # Trello, shared activity, shared checklists, and the document-folder
        # walk are independent. Running them together removes three stacked
        # network/disk waits from every uncached card open.
        trello_card, local_activity = {}, []
        with ThreadPoolExecutor(max_workers=4,
                                thread_name_prefix="workspace") as pool:
            checklist_future = pool.submit(pipeline_store.list_checklists, cid)
            activity_future = pool.submit(pipeline_store.list_activity, cid)
            document_future = pool.submit(
                self._document_signature_workspace,
                client, cid, summary.get("path") or "")
            if cid:
                import trello_client as tc
                trello_future = pool.submit(tc.get_card, cid)
            else:
                trello_future = pool.submit(lambda: {})
            checklists = checklist_future.result()
            local_activity = activity_future.result()
            documents = document_future.result()
            try:
                trello_card = trello_future.result() or {}
            except Exception as ex:
                summary["trello_error"] = str(ex)
        if cid:
            try:
                imported_checklists = [{
                    "id": cl.get("id") or "", "name": cl.get("name") or "Checklist",
                    "items": [{"id": item.get("id") or "",
                               "name": item.get("name") or "",
                               "complete": item.get("state") == "complete"}
                              for item in (cl.get("checkItems") or [])],
                } for cl in (trello_card.get("checklists") or [])]
                if imported_checklists:
                    saved = pipeline_store.save_checklists(
                        cid, imported_checklists, source="trello")
                    checklists = (saved.get("checklists")
                                  if saved.get("ok") else imported_checklists)
                attachments = [{"name": a.get("name") or "Attachment",
                                "url": a.get("url") or "",
                                "date": a.get("date") or ""}
                               for a in (trello_card.get("attachments") or [])]
                members = [m.get("fullName") or m.get("username") or ""
                           for m in (trello_card.get("members") or [])]
                # get_card already includes the latest 50 activity actions.
                # Re-fetching every historical comment here used as many as
                # 20 additional network calls each time a card opened. Older
                # comments remain in the shared activity table once imported.
                trello_comments = [action for action in (trello_card.get("actions") or [])
                                   if action.get("type") == "commentCard"]
                activity_import = []
                for action in trello_comments:
                    text = str((action.get("data") or {}).get("text") or "").strip()
                    if not text:
                        continue
                    actor = (action.get("memberCreator") or {}).get("fullName") or "Trello"
                    comment = {"id": action.get("id") or "", "text": text,
                               "actor": actor, "at": action.get("date") or "",
                               "source": "trello"}
                    comments.append(comment)
                    activity_import.append({
                        "action_type": "comment", "body": text,
                        "actor_name": actor, "source": "trello",
                        "external_id": comment["id"],
                        "happened_at": comment["at"],
                    })
                pipeline_store.add_activities(cid, activity_import)
            except Exception as ex:
                summary["trello_error"] = str(ex)
        # Preserve Linguar-only comments when Trello was unavailable. Avoid
        # duplicates for comments already mirrored by external action id.
        seen = {c.get("id") for c in comments if c.get("id")}
        for activity in local_activity:
            ext = activity.get("external_id") or ""
            if ext and ext in seen:
                continue
            if activity.get("action_type") == "comment":
                comments.append({"id": ext or activity.get("activity_key") or "",
                                 "text": activity.get("body") or "",
                                 "actor": activity.get("actor_name") or "Linguar Hub",
                                 "at": activity.get("happened_at") or "",
                                 "source": activity.get("source") or "linguar"})
        comments.sort(key=lambda c: c.get("at") or "", reverse=True)
        result = {"ok": True, "client": client, "card_id": cid,
                "selected_division": selected_division,
                "selected_trello_url": (f"https://trello.com/c/{cid}"
                                        if cid else ""),
                "audit": summary, "crm": crm, "info_sections": info_sections,
                "division_trello_cards": division_cards,
                "division_card_reconciliation": division_reconciliation,
                "checklists": checklists, "comments": comments,
                "attachments": attachments, "members": members,
                "documents": documents,
                "load_ms": round((time.monotonic() - started) * 1000)}
        if len(self._workspace_cache) >= 80:
            oldest = min(self._workspace_cache,
                         key=lambda key: self._workspace_cache[key][0])
            self._workspace_cache.pop(oldest, None)
        self._workspace_cache[workspace_key] = (time.monotonic(), result)
        return result

    def refresh_job_card_workspace(self, client: str, card_id: str = "",
                                   division: str = "") -> dict:
        """Explicit deep refresh; normal opens remain cache-friendly."""
        key = (client or "").strip().casefold()
        self._invalidate_workspace(client, card_id)
        self._audit_card_cache.pop(key, None)
        self._division_reconcile_cache.pop(key, None)
        for cache_key in list(self._document_cache):
            if not card_id or cache_key[0] == card_id:
                self._document_cache.pop(cache_key, None)
        return self.job_card_workspace(client, card_id, division)

    def job_card_workspace_fast(self, client: str, card_id: str = "",
                                division: str = "") -> dict:
        """Shared-data-first workspace used for an immediate card open.

        This deliberately avoids the live folder audit, Trello search/card
        calls, and network-drive walk. The frontend follows it with the full
        workspace request while the user can already read or edit CRM data.
        """
        started = time.monotonic()
        workspace_key = self._workspace_cache_key(client, card_id, division)
        cached_workspace = self._workspace_cache.get(workspace_key)
        if cached_workspace and time.monotonic() - cached_workspace[0] < 45:
            return {**cached_workspace[1], "cached": True,
                    "load_ms": round((time.monotonic() - started) * 1000)}
        if not (client or "").strip():
            return {"ok": False, "error": "client required"}
        audit_api = self._audit_api()
        summary = {"ok": True, "client": client, "found": True,
                   "form_issues": [], "photo_issues": [], "requirements": [],
                   "activity": [], "path": "", "trello_card_id": card_id or ""}
        crm = audit_api.crm_job_workspace(client, summary)
        division_result = audit_api.crm_division_trello_cards(client)
        division_cards = division_result.get("cards", [])
        from ems_db_common import normalize_division
        selected_division = normalize_division(division) if division else "EMS"
        selected = next((item for item in division_cards
                         if item.get("division") == selected_division), {})
        cid = str(selected.get("card_id") or "").strip()
        if not cid and selected_division == "EMS":
            cid = (card_id or "").strip()
        info_sections = []
        try:
            import job_settings
            job = ems_db.find_job_by_name(client) or {}
            values, grouped, order = job_settings.stored_values(job), {}, []
            for fid, section, _key, label, _core in job_settings.FIELDS:
                value = str(values.get(fid) or "").strip()
                if not value:
                    continue
                if section not in grouped:
                    grouped[section] = []
                    order.append(section)
                grouped[section].append({"id": fid, "label": label, "value": value})
            info_sections = [{"name": section.title(), "fields": grouped[section]}
                             for section in order]
        except Exception:
            pass
        comments = []
        for activity in pipeline_store.list_activity(cid):
            if activity.get("action_type") != "comment":
                continue
            comments.append({"id": activity.get("external_id") or
                             activity.get("activity_key") or "",
                             "external_id": activity.get("external_id") or "",
                             "text": activity.get("body") or "",
                             "actor": activity.get("actor_name") or "Linguar Hub",
                             "at": activity.get("happened_at") or "",
                             "source": activity.get("source") or "linguar"})
        return {"ok": True, "client": client, "card_id": cid,
                "selected_division": selected_division,
                "selected_trello_url": (f"https://trello.com/c/{cid}" if cid else ""),
                "audit": summary, "crm": crm, "info_sections": info_sections,
                "division_trello_cards": division_cards,
                "division_card_reconciliation": {"ok": True, "divisions": []},
                "checklists": pipeline_store.list_checklists(cid),
                "comments": comments, "attachments": [], "members": [],
                "documents": {"provider": "DocuSign", "request": {}, "files": [],
                              "connected": False},
                "deferred_loading": True,
                "load_ms": round((time.monotonic() - started) * 1000)}

    def _document_signature_workspace(self, client: str, card_id: str,
                                      job_path: str) -> dict:
        """Text-only view of signature state and files already on disk."""
        cache_key = (str(card_id or ""), os.path.abspath(job_path) if job_path else "")
        cached = self._document_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 120:
            return cached[1]
        pending = None
        try:
            import docusign_requests as dsr
            for entry in dsr.pending_requests():
                if ((card_id and entry.get("card_id") == card_id) or
                        str(entry.get("client") or "").casefold() ==
                        str(client or "").casefold()):
                    pending = entry
                    break
        except Exception:
            pass
        files = []
        root = os.path.abspath(job_path) if job_path else ""
        if root and os.path.isdir(root):
            for dirname, _dirs, names in os.walk(root):
                if "docs" not in dirname.casefold() and "paperwork" not in dirname.casefold():
                    continue
                for name in names:
                    if not name.casefold().endswith((".pdf", ".doc", ".docx")):
                        continue
                    full = os.path.join(dirname, name)
                    try:
                        modified = _dt.datetime.fromtimestamp(
                            os.path.getmtime(full)).isoformat(timespec="seconds")
                    except OSError:
                        modified = ""
                    low = (dirname + " " + name).casefold()
                    files.append({"name": name, "path": full,
                                  "modified_at": modified,
                                  "signed": ("signed" in low or
                                             "final paperwork" in low)})
                    if len(files) >= 100:
                        break
                if len(files) >= 100:
                    break
        files.sort(key=lambda item: item.get("modified_at") or "", reverse=True)
        result = {"provider": "DocuSign", "connected": False,
                  "connection_note": "Direct DocuSign connection is not configured yet",
                  "request": pending or {}, "files": files[:20],
                  "storage": "Official signed file stays in the X: OD job folder; only status and path are indexed"}
        self._document_cache[cache_key] = (time.monotonic(), result)
        return result

    def mark_docusign_sent(self, client: str, card_id: str = "",
                           customer_email: str = "") -> dict:
        """Record a manually-sent envelope using Job Information email."""
        try:
            import docusign_requests as dsr
            cid = (card_id or "").strip()
            if not cid:
                return {"ok": False, "error": "This job needs a linked Trello card for the current tracker"}
            entry = dsr.request(cid, client_name=client,
                                email_override=customer_email)
            if not entry:
                return {"ok": False, "error": "Could not record the DocuSign request"}
            return {"ok": True, "entry": entry}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_docusign(self) -> bool:
        return self.open_url("https://app.docusign.com/")

    def open_job_folder(self, client: str, path: str = "") -> dict:
        return self._audit_api().open_od_for_client(client, path)

    def open_document(self, path: str) -> dict:
        path = os.path.abspath(path or "")
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "document is no longer in that folder"}
        try:
            os.startfile(path)
            return {"ok": True}
        except OSError as ex:
            return {"ok": False, "error": str(ex)}

    def list_pics_stages(self, client: str) -> dict:
        return self._audit_api().list_pics_stages(client)

    def copy_pics_to_clipboard(self, client: str, stage: str = "") -> dict:
        return self._audit_api().copy_pics_to_clipboard(client, stage)

    def save_crm_work_environment(self, client: str, work_environment: str,
                                  stage: str, owner: str = "") -> dict:
        result = self._audit_api().save_crm_work_environment(
            client, work_environment, stage, owner)
        if result.get("ok"):
            self._invalidate_workspace(client=client)
        return result

    def crm_division_trello_cards(self, client: str) -> dict:
        return self._audit_api().crm_division_trello_cards(client)

    def pin_crm_division_trello(self, client: str, division: str,
                                card_id_or_url: str) -> dict:
        result = self._audit_api().pin_crm_division_trello(
            client, division, card_id_or_url)
        if result.get("ok"):
            self._invalidate_workspace(client=client)
        return result

    def unpin_crm_division_trello(self, client: str, division: str) -> dict:
        result = self._audit_api().unpin_crm_division_trello(client, division)
        if result.get("ok"):
            self._invalidate_workspace(client=client)
        return result

    def set_job_check_item(self, card_id: str, item_id: str,
                           complete: bool) -> dict:
        local = pipeline_store.set_check_item(card_id, item_id, complete)
        synced = False
        error = ""
        try:
            import trello_client as tc
            synced = bool(tc.set_check_item_state(
                card_id, item_id, "complete" if complete else "incomplete"))
            if not synced:
                error = "Trello did not accept the checklist update"
        except Exception as ex:
            error = str(ex)
        if synced:
            pipeline_store.mark_card_sync(card_id, ok=True)
        elif local.get("ok"):
            pipeline_store.mark_card_sync(card_id, ok=False, error=error)
        result = {"ok": bool(local.get("ok")) or synced, "saved_local": bool(local.get("ok")),
                "synced": synced, "warning": error if local.get("ok") and not synced else "",
                "error": "" if local.get("ok") or synced else (local.get("error") or error)}
        if result.get("ok"):
            self._invalidate_workspace(card_id=card_id)
            self._board_view_cache = None
        return result

    def post_job_comment(self, client: str, card_id: str, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "write a comment first"}
        actor = "Linguar Hub"
        try:
            import supabase_client
            user = supabase_client.current_user() or {}
            if user.get("id") and not user.get("display_name"):
                return {"ok": False, "error":
                        "Add your name in My Settings before commenting."}
            actor = supabase_client.actor_name(actor)
        except Exception:
            pass
        posted_action = None
        error = ""
        if card_id:
            try:
                import trello_client as tc
                posted_action = tc.post_comment(card_id, text)
                if not posted_action:
                    error = "Trello did not accept the comment"
            except Exception as ex:
                error = str(ex)
        external_id = str(posted_action.get("id") or "") if isinstance(
            posted_action, dict) else ""
        local = pipeline_store.add_activity(
            card_id, "comment", text, actor, external_id=external_id)
        posted = bool(posted_action)
        result = {"ok": bool(local) or posted, "posted_trello": posted,
                "warning": error if local and not posted else "",
                "comment": {"id": local.get("activity_key") or "",
                            "external_id": external_id,
                            "text": text, "actor": actor,
                            "at": local.get("happened_at") or _dt.datetime.now().isoformat(),
                            "source": "linguar"}}
        if result.get("ok"):
            self._invalidate_workspace(client, card_id)
        return result

    def edit_job_comment(self, client: str, comment_id: str,
                         source: str, text: str,
                         external_id: str = "") -> dict:
        clean = (text or "").strip()
        if not clean:
            return {"ok": False, "error": "a comment cannot be empty"}
        if source == "trello":
            result = self._audit_api().update_card_comment(client, comment_id, clean)
            if result.get("ok"):
                self._invalidate_workspace(client=client)
            return result
        result = pipeline_store.update_activity(comment_id, clean)
        if not result.get("ok"):
            return result
        trello_id = external_id or result.get("external_id") or ""
        if trello_id:
            synced = self._audit_api().update_card_comment(client, trello_id, clean)
            if not synced.get("ok"):
                self._invalidate_workspace(client=client)
                return {**result, "text": clean, "warning":
                        "Saved in Linguar Hub, but Trello did not update"}
        self._invalidate_workspace(client=client)
        return {**result, "text": clean, "synced_trello": bool(trello_id)}

    def delete_job_comment(self, client: str, comment_id: str,
                           source: str, external_id: str = "") -> dict:
        if source == "trello":
            result = self._audit_api().delete_card_comment(client, comment_id)
            if result.get("ok"):
                self._invalidate_workspace(client=client)
            return result
        result = pipeline_store.delete_activity(comment_id)
        if not result.get("ok"):
            return result
        trello_id = external_id or result.get("external_id") or ""
        if trello_id:
            synced = self._audit_api().delete_card_comment(client, trello_id)
            if not synced.get("ok"):
                self._invalidate_workspace(client=client)
                return {**result, "warning":
                        "Deleted in Linguar Hub, but Trello did not delete"}
        self._invalidate_workspace(client=client)
        return {**result, "synced_trello": bool(trello_id)}

    def save_job_log_update(self, client: str, entry: dict) -> dict:
        result = self._audit_api().save_crm_job_log(client, entry)
        if result.get("ok"):
            self._invalidate_workspace(client=client)
        return result

    def import_job_log_from_trello(self, client: str, card_id: str) -> dict:
        """Import recognized work events from the selected division card."""
        result = self._audit_api().import_crm_job_log_from_trello(client, card_id)
        if result.get("ok"):
            self._invalidate_workspace(client, card_id)
        return result

    def delete_job_log_update(self, client: str, entry_id: str) -> dict:
        result = self._audit_api().delete_crm_job_log(client, entry_id)
        if result.get("ok"):
            self._invalidate_workspace(client=client)
        return result

    def job_log_update_history(self, entry_id: str) -> dict:
        return self._audit_api().crm_job_log_history(entry_id)

    def flag_missing_card(self, card_id: str, client: str,
                          item_text: str, note: str = "") -> dict:
        """Record a missing-item flag + post a Trello comment straight
        to this card (card id known — no pin lookup). Mirrors the
        audit/snapshot flag-missing flow; we post our own 🚩 comment so
        the tracker's auto-comment is suppressed (post_comment=False)."""
        if not client or not item_text:
            return {"ok": False, "error": "client + item required"}
        try:
            try:
                from missing_items_tracker import capture_missing_items
                capture_missing_items(
                    client, missing=[item_text], stage="audit", note=note,
                    card_id=card_id or "", post_comment=False)
            except Exception:
                pass
            posted = False
            if card_id:
                try:
                    import trello_client as tc
                    body = f"🚩 **Flagged missing**: {item_text}"
                    if note:
                        body += f"\n\n{note}"
                    tc.post_comment(card_id, body)
                    posted = True
                except Exception:
                    posted = False
            self._invalidate_workspace(client, card_id)
            return {"ok": True, "posted_trello": posted}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def attach(self, window):
        """Stash the window handle so background tasks can push events
        back to JS via window.evaluate_js()."""
        self._window = window

    # ── Threshold editor (P2) ────────────────────────────────────────
    def get_thresholds(self) -> dict:
        """Live thresholds dict + per-stage default for the editor UI."""
        live = ps.get_thresholds()
        return {
            "stages": [
                {"key": s, "label": ps.STAGE_LABELS.get(s, s),
                 "days": int(live.get(s) or 0),
                 "default": int(ps.DEFAULT_STAGE_THRESHOLDS.get(s) or 0)}
                for s in ps.STAGES
            ],
        }

    def set_threshold(self, stage: str, days) -> dict:
        """Save a per-stage override. `days=null` resets to default."""
        try:
            d = None if days in (None, "") else int(days)
            ps.set_threshold(stage, d)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def reset_thresholds(self) -> dict:
        """Reset all overrides — every stage falls back to its default."""
        try:
            for s in ps.STAGES:
                ps.set_threshold(s, None)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── 🕒 Per-card timeline (mirrors Tk _show_timeline) ────────────
    def card_timeline(self, card_id: str) -> dict:
        """Return the stage-transition history for a card, ordered
        oldest → newest. Each entry: from_stage, to_stage, when
        (ISO), days_in_from. Used by the per-row timeline modal."""
        if not card_id:
            return {"ok": False, "error": "card_id required",
                    "transitions": []}
        try:
            import ems_db as _db
            history = _db.list_transitions(card_id=card_id, order="ASC") or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "transitions": []}
        out = []
        for h in history:
            out.append({
                "from_stage":     h.get("from_stage") or "",
                "to_stage":       h.get("to_stage") or "",
                "when":           h.get("when") or h.get("transition_at") or "",
                "days_in_from":   h.get("days_in_from") or 0,
            })
        return {"ok": True, "card_id": card_id,
                "transitions": out,
                "total": len(out)}

    # ── 📊 Export to Excel (mirrors Tk _export_to_excel) ────────────
    def export_to_excel(self) -> dict:
        """Write the currently-loaded pipeline rows to a .xlsx in the
        user's downloads folder, one sheet per stage. Mirrors Tk's
        _export_to_excel — same column order, same stage-sheet split.
        Opens the file in Excel on success.
        """
        try:
            import datetime as _dt2
            import os as _os
            import pipeline_stages as _ps
            rows = self._last_rows or []
            if not rows:
                return {"ok": False,
                        "error": "no rows — sync from Trello first"}
            try:
                import openpyxl
            except ImportError:
                return {"ok": False,
                        "error": "openpyxl not installed"}
            today = _dt2.date.today()
            default_name = (f"Pipeline {today.month}-{today.day}-"
                            f"{today.year % 100}.xlsx")
            out_dir = _os.path.join(_os.path.expanduser("~"), "Downloads")
            if not _os.path.isdir(out_dir):
                out_dir = _os.path.expanduser("~")
            path = _os.path.join(out_dir, default_name)
            # Disambiguate if same-day file exists already
            i = 1
            while _os.path.isfile(path):
                stem = default_name[:-5]
                path = _os.path.join(out_dir, f"{stem} ({i}).xlsx")
                i += 1
            wb = openpyxl.Workbook()
            wb.remove(wb.active)
            headers = ("Client", "Stage", "Days in Stage", "Age",
                        "Last Activity", "Owner", "Board", "Lane", "URL")
            for stage in _ps.STAGES:
                sheet_rows = [r for r in rows
                               if (r.get("current_stage") or "") == stage]
                label = _ps.STAGE_LABELS.get(stage, stage)[:31] or stage[:31]
                ws = wb.create_sheet(title=label)
                ws.append(headers)
                for r in sheet_rows:
                    ws.append([
                        r.get("client_display") or r.get("client") or "",
                        _ps.STAGE_LABELS.get(stage, stage),
                        r.get("days_in_stage") or 0,
                        r.get("age_days") or 0,
                        r.get("last_activity_iso") or "",
                        r.get("owner") or "",
                        r.get("board_name") or "",
                        r.get("lane") or "",
                        r.get("card_url") or "",
                    ])
            if not wb.sheetnames:
                wb.create_sheet(title="Empty")
            wb.save(path)
            try: _os.startfile(path)
            except Exception: pass
            return {"ok": True, "path": path,
                    "rows": len(rows),
                    "stages": len(wb.sheetnames)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Read-only data API ───────────────────────────────────────────
    def stages(self) -> list[dict]:
        """Stage labels in lifecycle order — drives the filter chips."""
        return [{"key": s, "label": ps.STAGE_LABELS.get(s, s)}
                for s in ps.STAGES]

    def lifecycle_rows(self) -> list[dict]:
        """Every active lifecycle row (plus paid within 30d), shaped
        for the frontend table. Read-only — no DB writes happen here.

        Also runs the self-heal backfill so legacy 0d-in-stage rows
        get their stage_entered_at corrected before the JS side
        renders day counts."""
        try:
            ems_db.backfill_stage_entered_dates()
        except Exception:
            pass
        try:
            ps.purge_skipped_lifecycle_rows()
        except Exception:
            pass
        try:
            rows = ems_db.lifecycle_list(paid_window_days=30)
        except Exception:
            return []
        shaped = [_row_to_jsdict(r) for r in rows]
        # Cache the shaped rows so export_to_excel doesn't have to
        # re-query the DB — and so the export matches exactly what
        # the user is currently looking at (same filter window).
        self._last_rows = shaped
        return shaped

    def stage_counts(self) -> dict:
        """{stage_key: count} for the filter chip badges."""
        try:
            return ems_db.lifecycle_counts_by_stage(paid_window_days=30)
        except Exception:
            return {}

    # ── Actions ──────────────────────────────────────────────────────
    def open_url(self, url: str) -> bool:
        """Open `url` in the user's default browser. Used for the
        Trello card jump on row double-click."""
        if not url:
            return False
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    def copy_to_clipboard(self, text: str) -> bool:
        """Clipboard write via the Win32 clipboard. NOT a throwaway
        tk.Tk() — Tk's delayed-rendering clipboard left a dead owner that
        froze the next paste in any app ('clipboard freezes constantly')."""
        if not text:
            return False
        from web_helpers import set_clipboard_text
        return set_clipboard_text(text)

    def sync_from_trello(self) -> dict:
        """Kick off a Trello workspace sync on a background thread.
        Returns immediately so the UI can show a spinner; progress +
        completion are pushed via window.evaluate_js() events."""
        if self._sync_running:
            return {"started": False, "reason": "sync already in progress"}
        self._sync_running = True

        def _bg():
            try:
                def _progress(i, n, board):
                    self._emit_js(
                        f"window.dispatchEvent(new CustomEvent("
                        f"'pipeline:sync-progress', "
                        f"{{detail: {{i: {i}, n: {n}, "
                        f"board: {self._jsstr(board)}}}}}));")
                result = ps.sync_workspace(progress_cb=_progress)
                self._emit_js(
                    f"window.dispatchEvent(new CustomEvent("
                    f"'pipeline:sync-done', "
                    f"{{detail: {{ok: true, "
                    f"cards: {result.get('cards', 0)}, "
                    f"boards: {result.get('boards', 0)}}}}}));")
            except Exception as ex:
                msg = self._jsstr(f"{type(ex).__name__}: {ex}")
                self._emit_js(
                    f"window.dispatchEvent(new CustomEvent("
                    f"'pipeline:sync-done', "
                    f"{{detail: {{ok: false, error: {msg}}}}}));")
            finally:
                self._sync_running = False
        _wh_run_bg(_bg)
        return {"started": True}

    # ── Bridge helpers ───────────────────────────────────────────────
    def _emit_js(self, js: str) -> None:
        # Forwards to BOTH the home shell window AND the iframe's
        # contentWindow so event listeners inside the embedded panel
        # actually receive the dispatch. Without this, sync events
        # fire silently and the UI looks frozen.
        try:
            import web_event
            web_event.dispatch(self._window, js)
        except Exception:
            pass

    def _jsstr(self, s: str) -> str:
        """Tiny JSON-string encoder for inline JS templates above."""
        import json
        return json.dumps(str(s))


def main(argv=None):
    api = Api()
    window = webview.create_window(
        title="Pipeline — Linguar Hub (web spike)",
        url=INDEX_HTML,
        js_api=api,
        width=1280, height=820,
        min_size=(720, 500),
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
