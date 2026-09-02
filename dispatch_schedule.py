"""Run-Doc-backed dispatch projections for desktop and mobile clients.

The daily Word document remains the scheduling source of truth for now.  This
module is the one seam that turns those files into safe, JSON-only records;
the Operations UI and mobile gateway should not parse run docs independently.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import re


def _key(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _claim_key(value: object) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _name_signature(value: object) -> tuple[str, ...]:
    """Match `First Last` Run Docs to `Last, First` job records."""
    return tuple(sorted(_key(value).split()))


def _tech_code(value: object) -> str:
    try:
        from audit_logic import initials_for_name
        return str(initials_for_name(str(value or "")) or "").strip().casefold()
    except Exception:
        return ""


class RunDocReader:
    """Production adapter for the existing run-doc finder and parser."""

    @staticmethod
    def read(day: date) -> dict:
        from run_doc import _find_run_doc_for_date
        from state_hub import hub as state_hub

        path = _find_run_doc_for_date(day)
        if not path:
            return {"exists": False, "editable": False, "jobs": []}
        jobs, run_date = state_hub.parse_run_doc(str(path))
        return {
            "exists": True,
            "editable": str(path).casefold().endswith(".docx"),
            "run_date": run_date,
            "jobs": list(jobs or []),
        }


class DispatchSchedule:
    """Build the schedule once, then filter it for a signed-in employee."""

    def __init__(self, reader=None, tech_email_provider=None):
        self._reader = reader or RunDocReader()
        if tech_email_provider is None:
            from persistence import get_tech_emails
            tech_email_provider = get_tech_emails
        self._tech_email_provider = tech_email_provider

    def load(self, jobs: list[dict], *, start: date | None = None,
             days: int = 7) -> dict:
        start = start or date.today()
        live_jobs = list(jobs or [])
        email_map = self._email_map()
        scheduled_ids: set[str] = set()
        rows = []
        warnings = []
        for offset in range(max(1, int(days))):
            current = start + timedelta(days=offset)
            try:
                document = self._reader.read(current) or {}
                run_jobs = list(document.get("jobs") or [])
                projected = [
                    self._assignment(current, item, live_jobs, email_map)
                    for item in run_jobs
                ]
                for item in projected:
                    if item.get("card_id"):
                        scheduled_ids.add(str(item["card_id"]))
                rows.append({
                    "date": current.isoformat(),
                    "label": "Today" if offset == 0 else current.strftime("%a"),
                    "exists": bool(document.get("exists")),
                    "editable": bool(document.get("editable")),
                    "jobs": projected,
                })
            except Exception as ex:
                warnings.append(f"{current.isoformat()}: {type(ex).__name__}: {ex}")
                rows.append({
                    "date": current.isoformat(),
                    "label": "Today" if offset == 0 else current.strftime("%a"),
                    "exists": False,
                    "editable": False,
                    "jobs": [],
                    "error": "Run Doc could not be read",
                })
        unscheduled = [
            job for job in live_jobs
            if not job.get("card_id") or str(job.get("card_id")) not in scheduled_ids
        ]
        return {
            "source": "run_doc",
            "days": rows,
            "unscheduled": unscheduled[:80],
            "unscheduled_count": len(unscheduled),
            "warnings": warnings,
        }

    def for_user(self, schedule: dict, *, email: str = "",
                 display_name: str = "") -> dict:
        """Return only assignments belonging to one authenticated employee."""
        email_key = str(email or "").strip().casefold()
        name_key = _key(display_name)
        result = deepcopy(schedule or {})
        for day in result.get("days") or []:
            day["jobs"] = [
                assignment for assignment in day.get("jobs") or []
                if self._belongs_to(assignment, email_key, name_key)
            ]
        # An employee dispatch never publishes the office-wide unscheduled tray.
        result["unscheduled"] = []
        result["unscheduled_count"] = 0
        result["employee"] = {
            "email": email_key,
            "display_name": str(display_name or "").strip(),
        }
        return result

    def _assignment(self, day: date, item: dict, jobs: list[dict],
                    email_map: dict[str, str]) -> dict:
        client = str(item.get("client") or "").strip() or "Unnamed Run Doc item"
        matches = self._matches(item, jobs)
        live = matches[0] if matches else {}
        techs = [str(value).strip() for value in item.get("techs") or [] if str(value).strip()]
        emails = [email_map.get(_key(tech), "") for tech in techs]
        emails = list(dict.fromkeys(value for value in emails if value))
        seed = "|".join((day.isoformat(), _key(client), _key(item.get("unit")),
                         _claim_key(item.get("claim_hint")), _key(item.get("section"))))
        projected = dict(live)
        projected.update({
            "assignment_id": hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
            "date": day.isoformat(),
            "client": client,
            "technicians": techs,
            "technician_emails": emails,
            "time_slot": str(item.get("time_slot") or "").strip(),
            "section": str(item.get("section") or "work").strip().lower(),
            "task": str(item.get("raw") or "").strip(),
            "tenant": str(item.get("tenant") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "claim_hint": str(item.get("claim_hint") or "").strip(),
            "new_loss": bool(item.get("new_loss")),
            "matched": bool(matches),
            "match_conflict": len(matches) > 1,
            "source": "run_doc",
        })
        return projected

    @staticmethod
    def _matches(item: dict, jobs: list[dict]) -> list[dict]:
        wanted = _key(item.get("client"))
        if not wanted:
            return []
        exact = []
        wanted_signature = _name_signature(item.get("client"))
        for job in jobs:
            raw_names = (
                job.get("client"), job.get("job_name"), job.get("account_client"),
            )
            names = {
                _key(job.get("client")),
                _key(job.get("job_name")),
                _key(job.get("account_client")),
            }
            signatures = {_name_signature(value) for value in raw_names if _key(value)}
            if wanted in names or (wanted_signature and wanted_signature in signatures):
                exact.append(job)
        if not exact:
            candidates = []
            for job in jobs:
                names = [_key(job.get("client")), _key(job.get("job_name"))]
                if any(name and (wanted in name or name in wanted) for name in names):
                    candidates.append(job)
            if len(candidates) == 1:
                exact = candidates
        claim = _claim_key(item.get("claim_hint"))
        if claim and len(exact) > 1:
            claimed = [job for job in exact if claim in _claim_key(job.get("claim_number"))]
            if claimed:
                exact = claimed
        return exact

    def _email_map(self) -> dict[str, str]:
        try:
            raw = self._tech_email_provider() or {}
        except Exception:
            raw = {}
        return {
            _key(name): str(email or "").strip().casefold()
            for name, email in raw.items() if _key(name) and str(email or "").strip()
        }

    @staticmethod
    def _belongs_to(assignment: dict, email_key: str, name_key: str) -> bool:
        emails = {str(value or "").strip().casefold()
                  for value in assignment.get("technician_emails") or []}
        names = {_key(value) for value in assignment.get("technicians") or []}
        account_code = _tech_code(name_key)
        tech_codes = {_tech_code(value) for value in assignment.get("technicians") or []}
        return bool((email_key and email_key in emails) or
                    (name_key and name_key in names) or
                    (account_code and account_code in tech_codes))
