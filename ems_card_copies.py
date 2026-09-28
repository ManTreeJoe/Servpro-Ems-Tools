"""Explicit EMS WIP/Estimating placements; comments are mirrored by the server."""
import re

# Verified main office boards. OC, Contents, Recon, Logs and AR are excluded.
MAIN_BOARDS = {
    "5d8b8f4621038a7a93d6b27d": "wip",
    "5d8b8fec49d37b1456a3f63b": "estimating",
}
_SOURCE = re.compile(
    r"\n\n\[OneLoss EMS source\]\(https://trello\.com/c/[0-9a-f]{24}"
    r"#comment-[0-9a-f]{24}\)$")


def is_mirrored_comment(comment):
    return bool(_SOURCE.search(str((comment.get("data") or {}).get("text") or "")))


def link_copy(client, source_id, copied_id):
    """Link an existing Trello clone without creating a second OneLoss job."""
    import ems_db
    import trello_client as tc
    source_id = tc.parse_card_identifier(source_id)
    copied_id = tc.parse_card_identifier(copied_id)
    if not source_id or not copied_id:
        raise ValueError("Choose the original EMS card and paste the copy's Trello link.")
    job = ems_db.find_job_by_name(client)
    if not job:
        raise ValueError("Save this job before linking its copy.")
    links = ems_db.get_links(job["canon_key"], "trello_card") or []
    fields = "name,idBoard,closed,shortLink,shortUrl"
    source = tc.get_card_lite(source_id, fields=fields) or {}
    target = tc.get_card_lite(copied_id, fields=fields) or {}
    aliases = {str(v or "").lower() for v in (source_id, source.get("id"), source.get("shortLink"))}
    if not any(str(row.get("link_value") or "").lower() in aliases for row in links):
        raise ValueError("The original card must already be linked to this job's EMS division.")
    roles = {MAIN_BOARDS.get(source.get("idBoard")), MAIN_BOARDS.get(target.get("idBoard"))}
    if roles != {"wip", "estimating"} or source.get("closed") is not False or target.get("closed") is not False:
        raise ValueError("Link one open EMS card on main Work in Progress and one on main Estimating.")
    if not source.get("id") or not target.get("id") or source["id"] == target["id"]:
        raise ValueError("Select two different EMS cards.")
    # A second copy on the same responsibility board would make pairing ambiguous.
    target_aliases = {target["id"].lower(), str(target.get("shortLink") or "").lower()}
    for alias in (aliases | target_aliases) - {""}:
        for kind in ("trello_card_contents", "trello_card_recon"):
            if ems_db.find_job_by_link(kind, alias):
                raise ValueError("Contents and Reconstruction cards do not share EMS comments.")
    for alias in target_aliases - {""}:
        owner = ems_db.find_job_by_link("trello_card", alias)
        if owner and owner.get("canon_key") != job["canon_key"]:
            raise ValueError("That card is already linked to another job. Review its job link first.")
    for row in links:
        value = str(row.get("link_value") or "").lower()
        if value in aliases or value in target_aliases:
            continue
        other = tc.get_card_lite(value, fields="idBoard,closed") or {}
        if other.get("idBoard") in MAIN_BOARDS and not other.get("closed"):
            raise ValueError("This EMS job already has another WIP/Estimating placement. Review its links first.")
    purpose = MAIN_BOARDS[target["idBoard"]]
    ems_db.set_link(job["canon_key"], "trello_card", target["id"],
                    added_by="ems_wip_estimating_copy",
                    metadata={"division": "EMS", "purpose": purpose,
                              "primary": False, "board": "Estimating" if purpose == "estimating" else "Work in Progress",
                              "comment_policy": "ems_wip_estimating", "source_card_id": source["id"]})
    return {"ok": True, "card_id": target["id"], "purpose": purpose,
            "url": target.get("shortUrl") or f"https://trello.com/c/{target['id']}",
            "comment_sync": "background", "division": "EMS"}
