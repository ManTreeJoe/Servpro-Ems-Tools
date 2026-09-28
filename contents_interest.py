"""Provision one durable Trello card per participating job division.

The original Contents module/operation names remain compatible with queued work.
"""
import hashlib
import json
import threading

import job_workflow

_DRAIN_LOCK = threading.Lock()
_ROUTES = {
    "EMS": ("work in progress", "tbs new loss/re-inspection", "ems - residential template"),
    "CONTENTS": ("contents", "new loss", "contents template"),
    "RECON": ("recon work in progress", "tbs new loss", None),
}


def scope():
    import config
    return str(config.active_department() or config.base_department() or "").upper()


def queue(job, division="CONTENTS", stage="interested"):
    from ems_db_common import normalize_division
    division = normalize_division(division)
    department = str(job.get("department") or scope()).upper()
    key = division.lower() + "-card:" + hashlib.sha256(
        (department + ":" + str(job.get("job_id") or job["canon_key"])).encode()).hexdigest()
    now = job_workflow._now()
    with job_workflow._connect() as conn:
        # Completed operations stay completed; repeated dropdown/owner saves
        # must never be interpreted as a request for a second division card.
        conn.execute("""INSERT INTO trello_outbox
          (operation_key,operation_type,job_key,entry_id,payload_json,created_at,updated_at)
          VALUES (?,?,?,'',?,?,?)
          ON CONFLICT(operation_key) DO UPDATE SET
            status=CASE WHEN trello_outbox.status='cancelled' THEN 'pending' ELSE trello_outbox.status END,
            payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
          (key, "contents.ensure_card" if division == "CONTENTS" else "division.ensure_card",
           job["canon_key"], json.dumps({"department": department, "division": division, "stage": stage,
                                            "client": job.get("display_name") or job["canon_key"]}), now, now))
        row = conn.execute("SELECT status,card_id FROM trello_outbox WHERE operation_key=?", (key,)).fetchone()
    return {"operation_key": key, "pending": row["status"] == "pending", "card_id": row["card_id"] or "", "division": division}


def cancel(job, division):
    from ems_db_common import normalize_division
    prefix = normalize_division(division).lower() + "-card:"
    with job_workflow._connect() as conn:
        conn.execute("UPDATE trello_outbox SET status='cancelled',updated_at=? "
                     "WHERE job_key=? AND operation_key LIKE ? AND status='pending'",
                     (job_workflow._now(), job["canon_key"], prefix + "%"))


def _ensure(operation):
    import ems_db
    import trello_client as tc
    import job_settings
    from ems_db_common import division_link_type
    division = operation["payload"].get("division", "CONTENTS")
    board_name, lane_name, template_name = _ROUTES[division]
    link_type = division_link_type("trello_card", division)
    key = operation["job_key"]
    job = ems_db.get_job(key)
    if not job:
        raise ValueError(f"The saved job is unavailable; {division} card creation is waiting.")
    if str(job.get("department") or scope()).upper() != scope():
        raise ValueError(f"Switch to this job's workspace to create its {division} card.")
    links = ems_db.get_links(key, link_type) or []
    if links:
        # Any existing division link is authoritative. Do not create another
        # card just because Trello is offline or the linked card is archived.
        def primary(link):
            metadata = link.get("metadata")
            if not isinstance(metadata, dict):
                metadata = json.loads(link.get("metadata_json") or "{}")
            return bool(metadata.get("primary", metadata.get("purpose", "primary") == "primary"))
        pinned = next((link for link in links if primary(link)), links[0])
        card = tc.get_card_lite(pinned["link_value"], fields="idBoard,shortUrl,closed") or {}
        if not card.get("id"):
            raise ValueError(f"The pinned {division} card could not be verified; a replacement was not created.")
        return card
    boards = [b for b in tc.list_boards() if b.get("name", "").strip().casefold() == board_name]
    if len(boards) != 1:
        raise ValueError(f"Could not identify one {division} board in this workspace.")
    board = boards[0]
    lists = tc._call(f"/boards/{board['id']}/lists", params={"filter": "open", "fields": "name,closed"})
    lanes = [l for l in lists if not l.get("closed") and l.get("name", "").strip().casefold() == lane_name]
    if len(lanes) != 1:
        raise ValueError(f"{division} needs one open {lane_name.upper()} lane.")
    marker = f"OneLoss {division.title()} reference: " + operation["operation_key"].split(":", 1)[1]
    cards = tc._call(f"/boards/{board['id']}/cards", params={
        "filter": "all", "fields": "name,desc,idBoard,closed,shortUrl", "limit": "1000"})
    if not isinstance(cards, list) or len(cards) >= 1000:
        raise ValueError(f"Could not verify the complete {division} card list; creation will retry.")
    matches = [c for c in cards if marker in (c.get("desc") or "").splitlines()]
    if len(matches) > 1:
        raise ValueError(f"More than one {division} card has this job's reference; review its links.")
    if matches:
        card = matches[0]  # Recover a successful POST whose response/pin save failed.
    else:
        templates = [c for c in cards if not c.get("closed") and
                     c.get("name", "").strip().casefold() == template_name]
        if template_name and len(templates) != 1:
            raise ValueError(f"Could not find one {template_name} on the {division} board.")
        values = job_settings.stored_values(job)
        desc = job_settings.render_desc((templates[0].get("desc") or "") if templates else "", values)
        name = str(job.get("display_name") or key)
        if division != "EMS" and not name.upper().endswith(" - " + division):
            name += " - " + division
        card = tc._call("/cards", method="POST", data={
            "idList": lanes[0]["id"],
            **({"idCardSource": templates[0]["id"], "keepFromSource": "all"} if templates else {}),
            "name": name, "pos": "bottom",
            "desc": desc.rstrip() + "\n\n" + marker})
    if not isinstance(card, dict) or not card.get("id") or card.get("idBoard") != board["id"]:
        raise ValueError(f"Trello did not confirm the {division} card. The saved request will retry.")
    ems_db.set_link(key, link_type, card["id"],
                    added_by="division_participation",
                    metadata={"division": division, "purpose": "primary", "primary": True,
                              "board": board["name"], "stage_at_creation": operation["payload"].get("stage", "interested")})
    return card


def drain():
    """Retry this workspace's durable requests. Provider work never blocks a save."""
    if not _DRAIN_LOCK.acquire(blocking=False):
        return []
    results = []
    try:
        for operation in job_workflow.pending(500):
            if operation["operation_type"] not in ("contents.ensure_card", "division.ensure_card"):
                continue
            if operation["payload"].get("department") != scope():
                continue
            try:
                card = _ensure(operation)
                with job_workflow._connect() as conn:
                    conn.execute("""UPDATE trello_outbox SET status='complete',card_id=?,
                      completed_at=?,updated_at=?,last_error=NULL WHERE operation_key=?""",
                      (card["id"], job_workflow._now(), job_workflow._now(), operation["operation_key"]))
                results.append({"ok": True, "job_key": operation["job_key"], "division": operation["payload"].get("division", "CONTENTS"),
                                "client": operation["payload"].get("client", ""),
                                "card_id": card["id"], "url": card.get("shortUrl") or f"https://trello.com/c/{card['id']}"})
            except Exception as ex:
                job_workflow.fail(operation["operation_key"], str(ex))
                results.append({"ok": False, "job_key": operation["job_key"], "division": operation["payload"].get("division", "CONTENTS"), "error": str(ex)})
    finally:
        _DRAIN_LOCK.release()
    return results
