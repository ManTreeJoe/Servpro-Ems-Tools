"""Read-optimized Operations Hub model shared by desktop and browser shells.

The interface deliberately stays small: bootstrap the operating picture, open
one client account, and hydrate or act on one job. Existing Trello, OD, and
database modules remain adapters behind this seam while Linguar Hub gradually
takes ownership.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import threading
import time


class OperationsHub:
    """Build compact JSON-only projections for the Operations UI."""

    def __init__(self, pipeline=None, clients=None, data=None, *, dispatch=None,
                 ttl: int = 30):
        if pipeline is None:
            from pipeline_web import Api as PipelineApi
            pipeline = PipelineApi()
        if clients is None:
            from clients_web import Api as ClientsApi
            clients = ClientsApi()
        if data is None:
            from operations_data import OperationsData
            data = OperationsData(ttl=ttl)
        if dispatch is None:
            from dispatch_schedule import DispatchSchedule
            dispatch = DispatchSchedule()
        self._pipeline = pipeline
        self._clients = clients
        self._data = data
        self._dispatch_schedule = dispatch
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
            data_future = pool.submit(self._data.snapshot, bool(force))
            board_result = boards_future.result()
            data_result = data_future.result()
        boards = list(board_result.get("boards") or []) if board_result.get("ok") else []
        clients = list(data_result.get("clients") or []) if data_result.get("ok") else []
        client_result = {"ok": bool(data_result.get("ok")),
                         "error": data_result.get("error") or ""}
        if not data_result.get("ok"):
            # A mapped OD can keep the directory useful while auth is fixed,
            # but it is visibly labelled as a fallback below and never
            # masquerades as shared database data.
            client_result = self._clients.list_clients("", "all", 500)
            clients = list(client_result.get("clients") or []) if client_result.get("ok") else []
            for client in clients:
                client.setdefault("source", "folder_fallback")
        refresh_warning = ""
        if not boards and prior:
            boards = list(prior.get("boards") or [])
            refresh_warning = (board_result.get("error") or
                               "Live refresh failed; showing the last operating picture")
        if not clients:
            clients = self._shared_clients()
        jobs = self._data.enrich_jobs(self._flatten_jobs(boards), data_result)
        if not clients:
            clients = self._clients_from_jobs(jobs)
        data_state = dict(data_result.get("state") or {})
        if not data_result.get("ok") and clients:
            data_state["fallback"] = "folders"
        dispatch = self._dispatch_schedule.load(jobs)
        overview = self._overview(jobs, clients)
        overview["due_today"] = len((dispatch.get("days") or [{}])[0].get("jobs") or [])
        result = {
            "ok": bool(board_result.get("ok") or client_result.get("ok")),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "load_ms": round((time.monotonic() - started) * 1000),
            "source": (data_state.get("source") if data_result.get("ok") else
                       board_result.get("source") or "local"),
            "pipeline_source": board_result.get("source") or "local",
            "data_state": data_state,
            "warnings": [message for message in (
                board_result.get("warning"), board_result.get("error"),
                data_result.get("error"), client_result.get("error"),
                refresh_warning,
                *(data_result.get("warnings") or []),
            ) if message],
            "overview": overview,
            "boards": boards,
            "jobs": jobs,
            "dispatch": dispatch,
            "clients": clients,
            "reports": self._reports(jobs),
            "tool_routes": __import__("operations_tools").browser_routes(),
        }
        with self._lock:
            self._cache = (time.monotonic(), result)
        return result

    @staticmethod
    def tool_routes() -> dict:
        """Tool navigation remains available even if live job data is down."""
        from operations_tools import browser_routes
        return {"ok": True, "routes": browser_routes()}

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
        """Resolve a job/card reference to its owning client account.

        Live board cards often carry a complete job title rather than the
        top-level client name (for example a management company, property,
        resident, and received date).  The Clients adapter already knows how
        to prove that relationship against the configured folder hierarchy;
        use that resolver before opening the account instead of asking the UI
        to guess by splitting the title.
        """
        requested = (name or "").strip()
        if not requested:
            return {"ok": False, "error": "Choose a client first."}
        shared = self._data.account(requested)
        if shared.get("ok"):
            return shared
        resolved = requested
        try:
            matches = self._clients.list_clients(requested, "all", 10)
            rows = list(matches.get("clients") or []) if matches.get("ok") else []
            exact = next((row for row in rows if
                          str(row.get("name") or "").casefold() ==
                          requested.casefold()), None)
            chosen = exact or (rows[0] if len(rows) == 1 else None)
            if chosen and str(chosen.get("name") or "").strip():
                resolved = str(chosen["name"]).strip()
        except Exception:
            # Shared-index-only hosts may not have an accessible folder root.
            # The account adapter can still return the database-backed record.
            pass
        result = self._clients.client_account(resolved)
        if result.get("ok"):
            result = dict(result)
            result["requested_reference"] = requested if requested != resolved else ""
            result["resolved_client_name"] = resolved
            result["data_source"] = "folder_fallback"
            result["shared_warning"] = shared.get("error") or ""
            result["data_state"] = shared.get("data_state") or {}
        return result

    @staticmethod
    def connections() -> dict:
        """Fast, non-secret connection cards for the signed-in employee."""
        try:
            import user_connections
            return {"ok": True, "connections": user_connections.statuses()}
        except Exception as ex:
            return {"ok": False, "connections": [], "error": str(ex)}

    @staticmethod
    def account_sign_in(email: str, password: str) -> dict:
        import user_connections
        return user_connections.sign_in(email, password)

    @staticmethod
    def account_sign_out() -> dict:
        import user_connections
        return user_connections.sign_out()

    @staticmethod
    def begin_connection(provider: str) -> dict:
        import user_connections
        return user_connections.begin(provider)

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
            section_name = str(section.get("name") or "Job details").strip()
            for field in section.get("fields") or []:
                value = str(field.get("value") or "").strip()
                if value:
                    fields.append({
                        "id": field.get("id") or "",
                        "label": field.get("label") or "Job detail",
                        "value": value,
                        "section": section_name,
                        "core": bool(field.get("core", True)),
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

    def field_note_templates(self, division: str = "EMS") -> dict:
        """Expose the same compact field-note forms to every client shell."""
        from field_notes import templates
        return {"ok": True, "templates": templates(division)}

    def save_field_note(self, client: str, note_type: str, values: dict,
                        division: str = "EMS", source_id: str = "") -> dict:
        """Save a technician note through the existing Job Log pipeline."""
        from field_notes import build_entry
        try:
            entry = build_entry(note_type, values, division=division,
                                source_id=source_id)
        except ValueError as ex:
            return {"ok": False, "error": str(ex)}
        result = self.save_job_update(client, entry)
        if result.get("ok"):
            return {**result, "note_type": note_type,
                    "entry": result.get("entry") or entry}
        return result

    def import_job_log(self, client: str, card_id: str = "") -> dict:
        """Bring the proven Trello-note importer into the new workspace."""
        result = self._pipeline.import_job_log_from_trello(
            (client or "").strip(), (card_id or "").strip())
        if not result.get("ok"):
            return result
        context = self.job_context(client, card_id)
        return {**result, "job_log": context.get("job_log") or [],
                "context_error": context.get("error") or ""}

    def set_job_requirement(self, client: str, requirement_key: str,
                            state: str, note: str = "",
                            details: dict | None = None,
                            card_id: str = "", division: str = "EMS") -> dict:
        """Save one requirement decision and return the refreshed progress.

        Returning the compact progress projection lets both shells update only
        the Requirements section; a checkbox must not force a full card or
        application refresh.
        """
        result = self._pipeline.set_job_requirement(
            (client or "").strip(), (requirement_key or "").strip(),
            (state or "").strip(), note or "",
            details if isinstance(details, dict) else {})
        if not result.get("ok"):
            return result
        context = self.job_context(client, card_id, division)
        return {**result, "progress": context.get("progress") or {},
                "context_error": context.get("error") or ""}

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
                        "job_id": card.get("job_id") or "",
                        "client_id": card.get("client_id") or "",
                        "claim_id": card.get("claim_id") or "",
                        "sync_error": card.get("sync_error") or "",
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

    def employee_dispatch(self, email: str = "", display_name: str = "",
                          force: bool = False) -> dict:
        """Return the Run Doc assignments for one authenticated employee.

        The mobile gateway must supply identity from its validated access
        token; clients must never choose the email they want to query.
        """
        schedule = self.bootstrap(force).get("dispatch") or {}
        filtered = self._dispatch_schedule.for_user(
            schedule, email=email, display_name=display_name)
        return {
            "source": "run_doc",
            "days": [{
                "date": day.get("date") or "",
                "label": day.get("label") or "",
                "assignments": [{
                    "id": item.get("assignment_id") or "",
                    "jobId": item.get("job_id") or item.get("card_id") or "",
                    "date": item.get("date") or day.get("date") or "",
                    "customer": item.get("client") or "",
                    "timeSlot": item.get("time_slot") or "",
                    "task": item.get("task") or "",
                    "section": item.get("section") or "work",
                    "technicians": list(item.get("technicians") or []),
                    "matched": bool(item.get("matched")),
                    "conflict": bool(item.get("match_conflict")),
                } for item in day.get("jobs") or []],
            } for day in filtered.get("days") or []],
        }

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
