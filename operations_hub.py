"""Read-optimized Operations Hub model shared by desktop and browser shells.

The interface deliberately stays small: bootstrap the operating picture, open
one client account, and hydrate or act on one job. Existing Trello, OD, and
database modules remain adapters behind this seam while Linguar Hub gradually
takes ownership.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import threading
import time


class OperationsHub:
    """Build compact JSON-only projections for the Operations UI."""

    def __init__(self, pipeline=None, clients=None, *, ttl: int = 30):
        if pipeline is None:
            from pipeline_web import Api as PipelineApi
            pipeline = PipelineApi()
        if clients is None:
            from clients_web import Api as ClientsApi
            clients = ClientsApi()
        self._pipeline = pipeline
        self._clients = clients
        self._ttl = max(5, int(ttl))
        self._cache = None
        self._lock = threading.RLock()

    def bootstrap(self, force: bool = False) -> dict:
        """Return the complete first-paint model in one call.

        The projection is cached briefly because board and network-folder
        adapters can be slow. A forced refresh is explicit and never happens
        simply because a user changes tabs.
        """
        with self._lock:
            if not force and self._cache and time.monotonic() - self._cache[0] < self._ttl:
                return {**self._cache[1], "cached": True}
            prior = self._cache[1] if self._cache else None
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="operations") as pool:
            boards_future = pool.submit(self._pipeline.board_view, bool(force))
            clients_future = pool.submit(self._clients.list_clients, "", "all", 500)
            board_result = boards_future.result()
            client_result = clients_future.result()
        boards = list(board_result.get("boards") or []) if board_result.get("ok") else []
        clients = list(client_result.get("clients") or []) if client_result.get("ok") else []
        refresh_warning = ""
        if not boards and prior:
            boards = list(prior.get("boards") or [])
            refresh_warning = (board_result.get("error") or
                               "Live refresh failed; showing the last operating picture")
        if not clients:
            clients = self._shared_clients()
        jobs = self._flatten_jobs(boards)
        if not clients:
            clients = self._clients_from_jobs(jobs)
        result = {
            "ok": bool(board_result.get("ok") or client_result.get("ok")),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "load_ms": round((time.monotonic() - started) * 1000),
            "source": board_result.get("source") or "local",
            "warnings": [message for message in (
                board_result.get("warning"), board_result.get("error"),
                client_result.get("error"), refresh_warning,
            ) if message],
            "overview": self._overview(jobs, clients),
            "boards": boards,
            "jobs": jobs,
            "dispatch": self._dispatch(jobs),
            "clients": clients,
            "reports": self._reports(jobs),
        }
        with self._lock:
            self._cache = (time.monotonic(), result)
        return result

    @staticmethod
    def _clients_from_jobs(jobs: list[dict]) -> list[dict]:
        """Last-resort browser directory from the live board projection."""
        found = {}
        for job in jobs:
            name = str(job.get("client") or "").strip()
            if not name:
                continue
            key = name.casefold()
            item = found.setdefault(key, {
                "name": name, "path": "", "job_count": 0,
                "divisions": [], "has_children": False, "source": "live_board",
            })
            item["job_count"] += 1
            division = job.get("division") or "EMS"
            if division not in item["divisions"]:
                item["divisions"].append(division)
        return sorted(found.values(), key=lambda item: item["name"].casefold())

    @staticmethod
    def _shared_clients() -> list[dict]:
        """Cloud/offline-index directory when this browser host has no OD.

        Website users should not need Nathan's drive mapping just to search a
        client. Folder-backed details enrich records when available; the job
        index remains the lightweight identity source everywhere else.
        """
        try:
            import ems_db
            rows = list(ems_db.iter_jobs() or [])
        except Exception:
            return []
        by_name = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("display_name") or row.get("name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            entry = by_name.setdefault(key, {
                "name": name, "path": "", "job_count": 0,
                "divisions": [], "has_children": False, "source": "job_index",
            })
            entry["job_count"] += 1
            environments = row.get("work_environments") or []
            for item in environments:
                division = str((item or {}).get("work_environment") or "").upper()
                if division in {"EMS", "CONTENTS", "RECON"} and division not in entry["divisions"]:
                    entry["divisions"].append(division)
            department = str(row.get("department") or "").upper()
            if department in {"EMS", "CONTENTS", "RECON"} and department not in entry["divisions"]:
                entry["divisions"].append(department)
        return sorted(by_name.values(), key=lambda item: item["name"].casefold())

    def client_account(self, name: str) -> dict:
        return self._clients.client_account((name or "").strip())

    def job_context(self, client: str, card_id: str = "",
                    division: str = "EMS") -> dict:
        """Return the fast job projection used to enrich an open drawer.

        Cards render immediately from ``bootstrap``. This slower adapter is
        called only after a user opens one card, so folder discovery and Job
        Info never hold up the board itself.
        """
        result = self._pipeline.job_card_workspace_fast(
            (client or "").strip(), (card_id or "").strip(),
            (division or "EMS").strip().upper())
        audit = result.get("audit") or {}
        crm = result.get("crm") or {}
        fields = []
        for section in result.get("info_sections") or []:
            for field in section.get("fields") or []:
                value = str(field.get("value") or "").strip()
                if value:
                    fields.append({
                        "id": field.get("id") or "",
                        "label": field.get("label") or "Job detail",
                        "value": value,
                    })
        return {
            "ok": bool(result.get("ok")),
            "error": result.get("error") or "",
            "client": result.get("client") or client,
            "card_id": result.get("card_id") or card_id,
            "division": result.get("selected_division") or division,
            "trello_url": result.get("selected_trello_url") or "",
            "path": audit.get("path") or "",
            "fields": fields,
            "job_log": list(crm.get("job_log") or []),
            "progress": crm.get("progress") or {},
            "load_ms": result.get("load_ms") or 0,
        }

    def job_action(self, action: str, job: dict) -> dict:
        """Route one clearly named job action to the existing adapter."""
        action = (action or "").strip().lower()
        job = job if isinstance(job, dict) else {}
        client = str(job.get("client") or "").strip()
        card_id = str(job.get("card_id") or "").strip()
        division = str(job.get("division") or "EMS").strip().upper()
        path = str(job.get("path") or "").strip()
        if not client:
            return {"ok": False, "error": "This job has no client name."}
        if action == "folder":
            return self._pipeline.open_job_folder(client, path)
        if action == "xa":
            opened = self._pipeline.open_xa_link(client, card_id)
            return {"ok": bool(opened), "error": "No XA link was found." if not opened else ""}
        if action == "companycam":
            opened = self._pipeline.open_companycam_link(client)
            return {"ok": bool(opened), "error": "No CompanyCam link was found." if not opened else ""}
        if action == "photo_report":
            return self._pipeline.open_companycam_report_editor(
                client, path, division)
        return {"ok": False, "error": "That job action is not available."}

    def save_job_update(self, client: str, entry: dict) -> dict:
        return self._pipeline.save_job_log_update(
            (client or "").strip(), entry if isinstance(entry, dict) else {})

    @staticmethod
    def _flatten_jobs(boards: list[dict]) -> list[dict]:
        jobs = []
        seen = set()
        division_by_board = {"contents": "CONTENTS", "logs": "EMS"}
        for board in boards:
            board_key = str(board.get("key") or "")
            if board_key == "logs":
                continue
            for lane in board.get("lanes") or []:
                for card in lane.get("cards") or []:
                    card_id = str(card.get("card_id") or "")
                    identity = card_id or f"{board_key}:{lane.get('name')}:{card.get('client')}"
                    if identity in seen:
                        continue
                    seen.add(identity)
                    division = division_by_board.get(board_key, "EMS")
                    jobs.append({
                        "card_id": card_id,
                        "client": card.get("client") or card.get("name") or "Unnamed job",
                        "url": card.get("url") or "",
                        "board_key": board_key,
                        "board": board.get("name") or board_key.upper(),
                        "lane": lane.get("name") or "Unassigned",
                        "division": division,
                        "divisions": [division],
                        "due": card.get("due") or "",
                        "overdue": bool(card.get("overdue")),
                        "days_in_lane": int(card.get("days_in_lane") or 0),
                        "stall": card.get("stall") or "none",
                        "loss_types": list(card.get("loss_types") or []),
                        "checklist": card.get("checklist") or {"done": 0, "total": 0},
                        "last_activity_at": card.get("last_activity_at") or "",
                        "sync_status": card.get("sync_status") or "",
                    })
        return jobs

    @staticmethod
    def _overview(jobs: list[dict], clients: list[dict]) -> dict:
        today = date.today().isoformat()
        due_today = sum(1 for job in jobs if job.get("due") == today)
        overdue = sum(1 for job in jobs if job.get("overdue"))
        stalled = sum(1 for job in jobs if job.get("stall") in {"warn", "bad"})
        return {
            "active_jobs": len(jobs), "clients": len(clients),
            "due_today": due_today, "overdue": overdue, "stalled": stalled,
            "needs_attention": overdue + stalled,
            "divisions": {
                division: sum(1 for job in jobs if job.get("division") == division)
                for division in ("EMS", "CONTENTS", "RECON")
            },
        }

    @staticmethod
    def _dispatch(jobs: list[dict]) -> dict:
        today = date.today()
        days = []
        for offset in range(7):
            current = today + timedelta(days=offset)
            iso = current.isoformat()
            scheduled = [job for job in jobs if job.get("due") == iso]
            days.append({
                "date": iso, "label": "Today" if offset == 0 else current.strftime("%a"),
                "jobs": scheduled,
            })
        unscheduled = [job for job in jobs if not job.get("due")]
        return {"days": days, "unscheduled": unscheduled[:80],
                "unscheduled_count": len(unscheduled)}

    @staticmethod
    def _reports(jobs: list[dict]) -> dict:
        lane_counts = {}
        division_counts = {"EMS": 0, "CONTENTS": 0, "RECON": 0}
        age_bands = {"0–3 days": 0, "4–7 days": 0, "8–14 days": 0, "15+ days": 0}
        for job in jobs:
            lane = job.get("lane") or "Unassigned"
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
            division = job.get("division") or "EMS"
            division_counts[division] = division_counts.get(division, 0) + 1
            age = int(job.get("days_in_lane") or 0)
            band = "0–3 days" if age <= 3 else "4–7 days" if age <= 7 else "8–14 days" if age <= 14 else "15+ days"
            age_bands[band] += 1
        return {
            "division_counts": division_counts,
            "lane_counts": [{"label": key, "value": value}
                            for key, value in sorted(lane_counts.items(), key=lambda item: (-item[1], item[0]))],
            "age_bands": [{"label": key, "value": value} for key, value in age_bands.items()],
        }
