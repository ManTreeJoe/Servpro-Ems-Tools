"""Shared, application-owned Pipeline storage.

This is the seam that lets Linguar Hub stop depending on Trello without a
flag-day migration.  Trello payloads are mirrored here now; later, native
Linguar cards use the same tables and Trello becomes an optional adapter.
Every public function fails soft when migration 011 has not been installed.
"""
from __future__ import annotations

import datetime as _dt
import json
import uuid

import supabase_client as _sb

_TABLES = ("crm_pipeline_boards", "crm_pipeline_lanes",
           "crm_pipeline_cards", "crm_pipeline_activity")


def _now():
    return _dt.datetime.now(_dt.UTC).isoformat()


def _rows(table, **params):
    out = _sb.rest("GET", table, params=params)
    return out if isinstance(out, list) else []


def _missing_schema(ex):
    s = str(ex).lower()
    return "pgrst205" in s or "could not find the table" in s


def available() -> bool:
    try:
        _rows("crm_pipeline_boards", select="board_key", limit="1")
        return True
    except Exception:
        return False


def _upsert(table, row):
    return _sb.rest("POST", table, body=row,
                    prefer="resolution=merge-duplicates")


def _card_rows(card_id: str, select: str = "*") -> list:
    """Find mirrored Trello or future native Linguar cards."""
    card_id = str(card_id or "").strip()
    if not card_id:
        return []
    rows = _rows("crm_pipeline_cards", external_id=f"eq.{card_id}",
                 select=select, limit="1")
    if rows:
        return rows
    return _rows("crm_pipeline_cards", card_key=f"eq.{card_id}",
                 select=select, limit="1")


def _decode_json(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value if isinstance(value, type(default)) else default


def checklist_summary(value) -> dict:
    """Normalize both old progress-only and full Linguar checklist records."""
    value = _decode_json(value, {})
    if "lists" not in value:
        return {"done": int(value.get("done") or 0),
                "total": int(value.get("total") or 0)}
    items = [item for group in (value.get("lists") or [])
             for item in (group.get("items") or [])]
    return {"done": sum(bool(item.get("complete")) for item in items),
            "total": len(items)}


def save_checklists(card_id: str, checklists: list, *, source="trello") -> dict:
    """Store complete checklist structure in Linguar Hub's card record."""
    try:
        cards = _card_rows(card_id, "card_key")
        if not cards:
            return {"ok": False, "error": "job is not in the shared Pipeline yet"}
        now = _now()
        value = {"version": 1, "lists": list(checklists or []),
                 "source": source, "updated_at": now}
        value["summary"] = checklist_summary(value)
        _sb.rest("PATCH", "crm_pipeline_cards",
                 params={"card_key": f"eq.{cards[0]['card_key']}"},
                 body={"checklist_json": value, "updated_at": now})
        return {"ok": True, "checklists": value["lists"],
                "summary": value["summary"]}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def list_checklists(card_id: str) -> list:
    try:
        cards = _card_rows(card_id, "checklist_json")
        value = _decode_json((cards[0] if cards else {}).get("checklist_json"), {})
        return list(value.get("lists") or [])
    except Exception:
        return []


def set_check_item(card_id: str, item_id: str, complete: bool) -> dict:
    """Update our durable checklist before any optional Trello write-back."""
    lists = list_checklists(card_id)
    found = False
    for group in lists:
        for item in group.get("items") or []:
            if str(item.get("id") or "") == str(item_id or ""):
                item["complete"] = bool(complete)
                found = True
                break
    if not found:
        return {"ok": False, "error": "checklist item is not imported yet"}
    result = save_checklists(card_id, lists, source="linguar")
    if result.get("ok"):
        try:
            cards = _card_rows(card_id, "card_key")
            _sb.rest("PATCH", "crm_pipeline_cards",
                     params={"card_key": f"eq.{cards[0]['card_key']}"},
                     body={"sync_status": "pending", "sync_error": None,
                           "updated_at": _now()})
        except Exception:
            pass
    return result


def mirror_boards(payload: dict) -> dict:
    """Upsert a shaped ``pipeline_web`` board payload into shared storage."""
    boards = list((payload or {}).get("boards") or [])
    now = _now()
    counts = {"boards": 0, "lanes": 0, "cards": 0}
    try:
        for board_pos, board in enumerate(boards):
            key = str(board.get("key") or "").strip()
            if not key or board.get("missing"):
                continue
            _upsert("crm_pipeline_boards", {
                "board_key": key, "name": board.get("name") or key,
                "position": board_pos, "source": "trello",
                "external_id": board.get("board_id") or None,
                "sync_status": "synced", "sync_error": None,
                "synced_at": now, "updated_at": now,
            })
            counts["boards"] += 1
            # Mark this board's old projection stale before reviving the
            # cards found in the current Trello response.
            _sb.rest("PATCH", "crm_pipeline_cards",
                     params={"board_key": f"eq.{key}"},
                     body={"archived": True, "updated_at": now})
            for lane_pos, lane in enumerate(board.get("lanes") or []):
                ext_lane = str(lane.get("list_id") or "")
                lane_key = f"trello:{ext_lane}" if ext_lane else f"{key}:{lane_pos}"
                _upsert("crm_pipeline_lanes", {
                    "lane_key": lane_key, "board_key": key,
                    "name": lane.get("name") or "Untitled lane",
                    "position": lane_pos, "source": "trello",
                    "external_id": ext_lane or None, "archived": False,
                    "updated_at": now,
                })
                counts["lanes"] += 1
                for card_pos, card in enumerate(lane.get("cards") or []):
                    ext_card = str(card.get("card_id") or "")
                    card_key = f"trello:{ext_card}" if ext_card else f"{lane_key}:{card_pos}"
                    _upsert("crm_pipeline_cards", {
                        "card_key": card_key, "board_key": key,
                        "lane_key": lane_key,
                        "title": card.get("client") or card.get("name") or "Untitled job",
                        "position": card_pos, "source": "trello",
                        "external_id": ext_card or None,
                        "external_url": card.get("url") or None,
                        "labels_json": card.get("loss_types") or [],
                        "due_at": card.get("due") or None,
                        "due_complete": bool(card.get("due_complete")),
                        "last_activity_at": card.get("last_activity_at") or None,
                        "sync_status": "synced", "sync_error": None,
                        "synced_at": now, "archived": False,
                        "created_at": now, "updated_at": now,
                    })
                    counts["cards"] += 1
        return {"ok": True, **counts}
    except Exception as ex:
        return {"ok": False, "schema_missing": _missing_schema(ex),
                "error": str(ex), **counts}


def load_boards(board_specs) -> dict:
    """Return the same JSON shape as ``pipeline_web.Api.board_view``."""
    try:
        boards = _rows("crm_pipeline_boards", select="*", order="position.asc")
        lanes = _rows("crm_pipeline_lanes", select="*", archived="eq.false",
                      order="position.asc")
        cards = _rows("crm_pipeline_cards", select="*", archived="eq.false",
                      order="position.asc")
    except Exception as ex:
        return {"ok": False, "schema_missing": _missing_schema(ex),
                "error": str(ex), "boards": []}
    by_board = {b.get("board_key"): b for b in boards}
    lanes_by_board = {}
    cards_by_lane = {}
    for lane in lanes:
        lanes_by_board.setdefault(lane.get("board_key"), []).append(lane)
    for card in cards:
        cards_by_lane.setdefault(card.get("lane_key"), []).append(card)
    out = []
    for key, expected_name in board_specs:
        b = by_board.get(key)
        if not b:
            continue
        shaped_lanes = []
        for lane in lanes_by_board.get(key, []):
            shaped_cards = []
            for c in cards_by_lane.get(lane.get("lane_key"), []):
                labels = c.get("labels_json") or []
                checklist = c.get("checklist_json") or {}
                if isinstance(labels, str):
                    try: labels = json.loads(labels)
                    except Exception: labels = []
                if isinstance(checklist, str):
                    try: checklist = json.loads(checklist)
                    except Exception: checklist = {}
                shaped_cards.append({
                    "card_id": c.get("external_id") or c.get("card_key"),
                    "name": c.get("title") or "", "client": c.get("title") or "",
                    "url": c.get("external_url") or "",
                    "list_id": lane.get("external_id") or lane.get("lane_key"),
                    "lane": lane.get("name") or "", "loss_types": labels,
                    "checklist": checklist_summary(checklist), "due": c.get("due_at") or "",
                    "due_complete": bool(c.get("due_complete")), "overdue": False,
                    "days_in_lane": 0, "stall": "none",
                    "sync_status": c.get("sync_status") or "local",
                })
            shaped_lanes.append({"list_id": lane.get("external_id") or lane.get("lane_key"),
                                 "name": lane.get("name") or "",
                                 "count": len(shaped_cards), "cards": shaped_cards})
        out.append({"key": key, "name": b.get("name") or expected_name,
                    "board_id": b.get("external_id") or "",
                    "lanes": shaped_lanes, "sync_status": b.get("sync_status") or "local"})
    return {"ok": bool(out), "boards": out, "source": "shared",
            "error": "" if out else "shared Pipeline is empty"}


def move_card(external_card_id: str, external_lane_id: str) -> dict:
    """Move the shared card first and mark it pending for the Trello adapter."""
    try:
        lanes = _rows("crm_pipeline_lanes", external_id=f"eq.{external_lane_id}",
                      select="lane_key,board_key", limit="1")
        if not lanes:
            return {"ok": False, "error": "destination lane is not mirrored yet"}
        lane = lanes[0]
        _sb.rest("PATCH", "crm_pipeline_cards",
                 params={"external_id": f"eq.{external_card_id}"},
                 body={"lane_key": lane["lane_key"], "board_key": lane["board_key"],
                       "sync_status": "pending", "sync_error": None,
                       "updated_at": _now()})
        return {"ok": True}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def mark_card_sync(external_card_id: str, *, ok: bool, error: str = "") -> None:
    try:
        _sb.rest("PATCH", "crm_pipeline_cards",
                 params={"external_id": f"eq.{external_card_id}"},
                 body={"sync_status": "synced" if ok else "conflict",
                       "sync_error": None if ok else error,
                       "synced_at": _now() if ok else None,
                       "updated_at": _now()})
    except Exception:
        pass


def add_activity(external_card_id: str, action_type: str, body: str,
                 actor_name: str = "", *, source: str = "linguar",
                 external_id: str = "") -> dict:
    """Append one permanent card activity; returns empty when v11 is absent."""
    try:
        cards = _rows("crm_pipeline_cards",
                      external_id=f"eq.{external_card_id}",
                      select="card_key", limit="1")
        if not cards:
            return {}
        now = _now()
        key = f"{source}:{external_id}" if external_id else f"linguar:{uuid.uuid4()}"
        row = {"activity_key": key, "card_key": cards[0]["card_key"],
               "action_type": action_type, "body": body,
               "actor_name": actor_name, "happened_at": now,
               "source": source, "external_id": external_id or None,
               "metadata_json": {}, "created_at": now}
        _upsert("crm_pipeline_activity", row)
        return row
    except Exception:
        return {}


def list_activity(external_card_id: str, *, limit: int = 100) -> list:
    try:
        cards = _rows("crm_pipeline_cards",
                      external_id=f"eq.{external_card_id}",
                      select="card_key", limit="1")
        if not cards:
            return []
        return _rows("crm_pipeline_activity",
                     card_key=f"eq.{cards[0]['card_key']}", select="*",
                     order="happened_at.desc", limit=str(limit))
    except Exception:
        return []


def update_activity(activity_key: str, body: str) -> dict:
    """Edit a Linguar-owned activity without rewriting imported history."""
    key, clean = str(activity_key or "").strip(), str(body or "").strip()
    if not key or not clean:
        return {"ok": False, "error": "comment and activity id are required"}
    try:
        rows = _rows("crm_pipeline_activity", activity_key=f"eq.{key}",
                     select="activity_key,source,external_id", limit="1")
        if not rows:
            return {"ok": False, "error": "comment was not found"}
        if rows[0].get("source") != "linguar":
            return {"ok": False, "error": "imported comments must be edited at their source"}
        _sb.rest("PATCH", "crm_pipeline_activity",
                 params={"activity_key": f"eq.{key}"}, body={"body": clean})
        return {"ok": True, "activity_key": key, "body": clean,
                "external_id": rows[0].get("external_id") or ""}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def delete_activity(activity_key: str) -> dict:
    """Delete one Linguar-owned activity; imported Trello rows are protected."""
    key = str(activity_key or "").strip()
    if not key:
        return {"ok": False, "error": "comment was not identified"}
    try:
        rows = _rows("crm_pipeline_activity", activity_key=f"eq.{key}",
                     select="activity_key,source,external_id", limit="1")
        if not rows:
            return {"ok": False, "error": "comment was not found"}
        if rows[0].get("source") != "linguar":
            return {"ok": False, "error": "imported comments must be deleted at their source"}
        _sb.rest("DELETE", "crm_pipeline_activity",
                 params={"activity_key": f"eq.{key}"})
        return {"ok": True, "deleted": True,
                "external_id": rows[0].get("external_id") or ""}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
