"""Local, read-only export of the exact Job Log displayed in a workspace."""
from datetime import date


def render_job_log(path, payload):
    from snapshot_logic import render_snapshot

    rows = []
    for entry in sorted(payload.get("entries") or [],
                        key=lambda e: (str(e.get("work_date") or ""),
                                       str(e.get("created_at") or ""))):
        if entry.get("deleted"):
            continue
        day = str(entry.get("work_date") or "")
        try:
            parsed = date.fromisoformat(day)
            weekday = parsed.strftime("%A")
            day = f"{parsed.month}/{parsed.day}/{str(parsed.year)[2:]}"
        except ValueError:
            weekday = ""
        activity = str(entry.get("work_type") or "Job update")
        if entry.get("status"):
            activity += " - " + str(entry["status"]).replace("_", " ")
        if entry.get("note"):
            activity += ": " + str(entry["note"])
        if entry.get("equipment"):
            activity += " | Equipment / readings: " + str(entry["equipment"])
        rows.append(dict(date=day, weekday=weekday, activity=activity,
                         techs=entry.get("technicians") or ""))
    render_snapshot(path, insured=payload["client"],
                    carrier=payload.get("carrier") or "",
                    dol=payload.get("dol") or "", logs=rows,
                    report_title=f"{payload.get('division') or 'EMS'} Job Log")
