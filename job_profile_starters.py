"""Reviewed Trello checklist copies. Never writes to Trello or existing profiles."""
import json
from pathlib import Path


def starters():
    sources = json.loads(Path(__file__).with_name("job_profile_sources.json").read_text(encoding="utf-8"))
    rows = []
    for source in sources:
        name = source["name"].split(" - (", 1)[0].replace(" Template", "")
        variants = (False, True) if source["id"] == "6a1255c6f609b36a72b4c1f5" else (False,)
        for state_farm in variants:
            items = []
            for checklist in source["checklists"]:
                group = checklist["name"].strip()
                # These are alternatives/scope selections, not mandatory work.
                conditional = group.upper() in ("SERVICES", "SPECIALTY ITEMS") or group.upper().startswith("CONTENTS")
                section = ""
                for raw in checklist["items"]:
                    label = raw.strip()
                    if label.startswith("**"):
                        section = label.strip("* ")
                        continue
                    if "STATE FARM" in label.upper() and not state_farm:
                        continue
                    if state_farm and group == "INITIAL - ADMIN" and label == "ATP":
                        continue
                    # Schedule replaces the retired Run workflow.
                    label = "Schedule" if label == "RUN" else label
                    prefix = "If applicable · " if conditional else ""
                    items.append(prefix + " · ".join(p for p in (group, section, label) if p))
            rows.append({"starter_id": source["id"] + ("-state-farm" if state_farm else ""),
                         "name": "EMS - State Farm" if state_farm else name,
                         "payer_type": "any", "division": "Any", "loss_type": None,
                         "carrier_or_client": "State Farm" if state_farm else None,
                         "active": False, "required_items": items,
                         "source_url": source["url"], "source_name": source["name"]})
    return sorted(rows, key=lambda row: row["name"].casefold())
