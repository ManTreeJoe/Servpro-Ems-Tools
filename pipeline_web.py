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
import os
import sys
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
    lanes = []
    for l in lists:
        lname = (l.get("name") or "").strip()
        if _is_noise_lane(lname):
            continue
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
    }


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

    # ── 🗂 Board view + drag-move + per-card audit actions ───────────
    def board_view(self) -> dict:
        """Live multi-board kanban payload pulled fresh from Trello. Each
        board → its open lanes (noise lanes filtered) → the open cards in
        each lane, shaped for the card UI. No DB; always current."""
        import trello_client as tc
        import pipeline_stages as ps
        try:
            boards_by_name = {
                (b.get("name") or "").strip().upper(): b
                for b in (tc.list_boards() or [])}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        out = [_build_board(tc, ps, key, bname,
                            boards_by_name.get(bname.strip().upper()))
               for key, bname in BOARD_SPECS]
        return {"ok": True, "boards": out}

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
        return {"ok": True, "board": board}

    def move_card(self, card_id: str, list_id: str) -> dict:
        """Move a card to another lane on the REAL Trello board. The
        frontend confirms before calling this (drag-to-move with a
        'Move X to <lane>?' prompt)."""
        if not card_id or not list_id:
            return {"ok": False, "error": "card_id + list_id required"}
        try:
            import trello_client as tc
            ok = tc.move_card(card_id, list_id)
            return {"ok": True} if ok else {
                "ok": False, "error": "Trello rejected the move"}
        except Exception as ex:
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
        try:
            res = self._audit_api().audit_one_job(client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not res or res.get("ok") is False:
            return {"ok": False,
                    "error": (res or {}).get("error") or "audit failed"}
        row = res.get("row") or {}
        return {
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
        }

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
