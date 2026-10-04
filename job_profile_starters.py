"""Reviewed Trello checklist copies. Never writes to Trello or existing profiles."""
import json
from pathlib import Path


def starters():
    sources = json.loads(Path(__file__).with_name("job_profile_sources.json").read_text(encoding="utf-8"))
    rows = []
    for source in sources:
        name = source["name"].split(" - (", 1)[0].replace(" Template", "")
        # State Farm is its own reviewed template, not a synthetic Residential
        # variant. Its authorization-to-perform and authorization-to-pay forms
        # are distinct obligations and must both survive the starter import.
        state_farm = source["id"] == "6abff02d164361290cce80c6"
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
                # Schedule replaces the retired Run workflow.
                label = "Schedule" if label == "RUN" else label
                prefix = "If applicable · " if conditional else ""
                items.append(prefix + " · ".join(p for p in (group, section, label) if p))
        rows.append({"starter_id": source["id"],
                     "name": name,
                     "payer_type": "any", "division": "Any", "loss_type": None,
                     "carrier_or_client": "State Farm" if state_farm else None,
                     "active": False, "required_items": items,
                     "source_url": source["url"], "source_name": source["name"]})
    return sorted(rows, key=lambda row: row["name"].casefold())
