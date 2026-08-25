"""Structured, append-only Snapshot revisions over the shared job DB."""
from __future__ import annotations

import datetime as _dt
import uuid

import ems_db
from ems_db_common import EVENT_SNAPSHOT_REVISION


def _job(client: str) -> dict:
    row = ems_db.find_job_by_name(client)
    if row:
        return row
    # Snapshot can be the first workflow to see a manually typed job.
    ems_db.upsert_job(display_name=(client or "").strip())
    return ems_db.find_job_by_name(client) or {}


def list_revisions(client: str, limit: int = 100) -> list[dict]:
    row = _job(client)
    key = row.get("canon_key") or ""
    if not key:
        return []
    events = ems_db.list_events(key, EVENT_SNAPSHOT_REVISION, limit=limit)
    out = []
    for event in events:
        payload = dict(event.get("payload") or {})
        payload.setdefault("created_at", event.get("event_at") or "")
        payload.setdefault("revision", 0)
        out.append(payload)
    return out


def save_revision(client: str, data: dict, *, pdf_path: str = "",
                  card_id: str = "", source_refs: dict | None = None) -> dict:
    row = _job(client)
    key = row.get("canon_key") or ""
    if not key:
        return {"ok": False, "error": "job could not be resolved"}
    previous = list_revisions(client, limit=1000)
    revision = max([int(r.get("revision") or 0) for r in previous] or [0]) + 1
    structured = {
        "snapshot_id": str(uuid.uuid4()),
        "revision": revision,
        "status": "generated",
        "created_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "job": client,
        "data": dict(data or {}),
        "rendered_text": render_text(data or {}),
        "pdf_path": pdf_path,
        "card_id": card_id,
        "source_refs": dict(source_refs or {}),
    }
    ems_db.log_event(key, EVENT_SNAPSHOT_REVISION, payload=structured)
    return {"ok": True, "snapshot_id": structured["snapshot_id"],
            "revision": revision, "record": structured}


def render_text(data: dict) -> str:
    lines = [
        f"Insured: {data.get('insured') or ''}",
        f"Carrier: {data.get('carrier') or ''}",
        f"Date of loss: {data.get('dol') or ''}",
        f"First visit: {data.get('first_visit') or data.get('first') or ''}",
        f"Cause: {data.get('cause') or ''}",
    ]
    comments = data.get("comments") or ""
    if comments:
        lines.append(f"Comments: {comments}")
    for row in data.get("subs") or []:
        lines.append("Sub: " + " | ".join(str(row.get(k) or "")
                                           for k in ("date", "activity", "techs")))
    for row in data.get("logs") or []:
        lines.append("Log: " + " | ".join(str(row.get(k) or "")
                                           for k in ("date", "activity", "techs")))
    return "\n".join(lines)
