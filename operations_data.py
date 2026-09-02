"""Authoritative structured data for the Operations Hub.

The Hub used to ask the folder browser for clients and the Pipeline for jobs.
That made two projections look authoritative even though both are adapters:
folders are document storage and Trello is transitional workflow evidence.

This module is the seam for the real record hierarchy.  It reads the shared
Supabase job graph first, supports both the installed v9 schema and the future
v11 Client/Claim tables, and labels every fallback honestly.  No caller needs
to know which schema generation is currently installed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import re
import threading
import time

from ems_db_common import canon_key


_DIVISIONS = {"EMS": "EMS", "CONTENTS": "CONTENTS", "RECON": "RECON"}


def _division(value) -> str:
    return _DIVISIONS.get(str(value or "").strip().upper(), "")


def _metadata(row: dict) -> dict:
    value = (row or {}).get("metadata")
    if isinstance(value, dict):
        return value
    value = (row or {}).get("metadata_json")
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _display_date(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for pattern in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y",
                    "%m-%d-%Y", "%m.%d.%Y", "%m/%d/%y", "%m-%d-%y",
                    "%m.%d.%y"):
        try:
            return datetime.strptime(raw[:19], pattern).strftime("%m-%d-%y")
        except ValueError:
            continue
    return raw


def _card_key(value) -> str:
    raw = str(value or "").strip().lower().rstrip("/")
    if "/c/" in raw:
        raw = raw.split("/c/", 1)[1].split("/", 1)[0]
    return raw


class OperationsData:
    """Return Client -> Job/Claim -> Division projections from one interface."""

    def __init__(self, db=None, supabase=None, *, ttl: int = 30):
        if db is None:
            import ems_db
            db = ems_db
        if supabase is None:
            import supabase_client
            supabase = supabase_client
        self._db = db
        self._sb = supabase
        self._ttl = max(5, int(ttl))
        self._cache = None
        self._lock = threading.RLock()

    def snapshot(self, force: bool = False) -> dict:
        """Load the shared identity graph once for board and client callers."""
        with self._lock:
            if (not force and self._cache and
                    time.monotonic() - self._cache[0] < self._ttl):
                return self._cache[1]

        backend = ""
        try:
            backend = str(self._db.backend_name() or "").lower()
        except Exception:
            backend = "supabase"
        health = {"configured": backend != "supabase", "reachable": True,
                  "signed_in": backend != "supabase", "user": None,
                  "error": ""}
        if backend == "supabase":
            health = self._sb.health()
            if not health.get("signed_in"):
                result = self._empty(
                    "auth_required",
                    health.get("error") or "Sign in to load shared client and job data.",
                    health)
                with self._lock:
                    self._cache = (time.monotonic(), result)
                return result

        started = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=7,
                                    thread_name_prefix="operations-data") as pool:
                jobs_future = pool.submit(self._db.iter_jobs)
                children_future = pool.submit(self._db.all_children)
                aliases_future = pool.submit(self._db.all_aliases)
                if backend == "supabase":
                    env_future = pool.submit(self._rows_all, "crm_job_departments")
                    clients_future = pool.submit(self._optional_rows, "crm_clients")
                    claims_future = pool.submit(self._optional_rows, "crm_claims")
                    log_future = pool.submit(self._optional_table,
                                             "crm_job_log_entries")
                else:
                    env_future = pool.submit(self._local_environments)
                    clients_future = claims_future = log_future = None
                jobs = list(jobs_future.result() or [])
                children = list(children_future.result() or [])
                aliases = list(aliases_future.result() or [])
                environments = list(env_future.result() or [])
                crm_clients, clients_ready = (([], False) if clients_future is None
                                               else clients_future.result())
                crm_claims, claims_ready = (([], False) if claims_future is None
                                             else claims_future.result())
                _, job_log_ready = (([], False) if log_future is None
                                     else log_future.result())
        except Exception as ex:
            result = self._empty(
                "shared_error" if backend == "supabase" else "local_error",
                f"{type(ex).__name__}: {ex}", health)
            with self._lock:
                self._cache = (time.monotonic(), result)
            return result

        result = self._shape(
            jobs, children, aliases, environments,
            crm_clients if clients_ready else [],
            crm_claims if claims_ready else [],
            source="supabase" if backend == "supabase" else "local",
        )
        client_schema = bool(clients_ready and claims_ready)
        result.update({
            "ok": True,
            "load_ms": round((time.monotonic() - started) * 1000),
            "state": {
                "mode": "shared" if backend == "supabase" else "local",
                "source": "supabase" if backend == "supabase" else "local_sqlite",
                "signed_in": bool(health.get("signed_in")),
                "user": health.get("user"),
                "client_model": ("crm_v11" if client_schema and crm_clients
                                 else "crm_v11_empty" if client_schema
                                 else "job_index_v9"),
                "job_log_model": "crm_v10" if job_log_ready else "event_history",
                "error": "",
            },
            "warnings": [message for message in (
                ("Client/claim tables are not installed in Supabase yet; "
                 "using the shared v9 job hierarchy."
                 if backend == "supabase" and not client_schema else ""),
                ("The editable Job Log tables are not installed yet; "
                 "history is using the shared event fallback."
                 if backend == "supabase" and not job_log_ready else ""),
            ) if message],
        })
        with self._lock:
            self._cache = (time.monotonic(), result)
        return result

    def enrich_jobs(self, jobs: list[dict], snapshot: dict | None = None) -> list[dict]:
        """Attach permanent Supabase identity to transient Pipeline cards."""
        data = snapshot or self.snapshot()
        if not data.get("ok"):
            return [{**job, "data_source": job.get("data_source") or "pipeline",
                     "identity_state": "shared_unavailable"} for job in jobs]
        by_id = data["_jobs_by_id"]
        by_key = data["_jobs_by_key"]
        aliases = data["_aliases"]
        children_by_card = data["_children_by_card"]
        children_by_name = data["_children_by_name"]
        accounts = data["_accounts_by_key"]
        out = []
        for original in jobs:
            item = dict(original)
            row = None
            child = None
            supplied_job_id = str(item.get("job_id") or "")
            if supplied_job_id:
                row = by_id.get(supplied_job_id)
            if row is None:
                child = children_by_card.get(_card_key(item.get("card_id")))
                if child:
                    row = by_key.get(child.get("parent_canon"))
            title_key = canon_key(item.get("client") or item.get("title") or "")
            if row is None:
                target = aliases.get(title_key) or title_key
                row = by_key.get(target)
            if row is None and title_key in children_by_name:
                child = children_by_name[title_key]
                row = by_key.get(child.get("parent_canon"))
            if row is None:
                item.update({"data_source": "pipeline", "identity_state": "unlinked"})
                out.append(item)
                continue
            account = accounts.get(row.get("_account_key")) or {}
            divisions = list(row.get("_divisions") or [])
            current_division = _division(item.get("division"))
            if current_division and current_division not in divisions:
                divisions.append(current_division)
            item.update({
                "job_id": row.get("job_id") or "",
                "canon_key": row.get("canon_key") or "",
                "account_client": account.get("name") or row.get("display_name") or "",
                "job_name": child.get("name") if child else row.get("display_name") or item.get("client"),
                "claim_number": row.get("claim_number") or "",
                "carrier": row.get("carrier") or "",
                "date_of_loss": row.get("date_of_loss") or "",
                "date_received": row.get("date_received") or "",
                "lifecycle_stage": row.get("lifecycle_stage") or "",
                "job_type": row.get("job_type") or "",
                "priority": row.get("priority") or "",
                "divisions": divisions or item.get("divisions") or [],
                "data_source": data.get("state", {}).get("source") or "supabase",
                "identity_state": "linked",
            })
            out.append(item)
        return out

    def account(self, reference: str, snapshot: dict | None = None) -> dict:
        """Resolve any job/claim reference to its owning client account."""
        requested = str(reference or "").strip()
        if not requested:
            return {"ok": False, "error": "Choose a client first."}
        data = snapshot or self.snapshot()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("error") or
                    "Shared client data is unavailable.",
                    "data_state": data.get("state") or {}}
        key = canon_key(requested)
        account_key = data["_reference_to_account"].get(key)
        if not account_key:
            account_key = data["_reference_to_account"].get(requested.casefold())
        account = data["_accounts_by_key"].get(account_key or "")
        if not account:
            return {"ok": False, "error": "This reference is not linked to a shared client yet.",
                    "data_state": data.get("state") or {}}
        client = dict(account)
        jobs = client.pop("_jobs", [])
        parent_key = client.get("key") or ""
        logs = []
        if parent_key:
            try:
                logs = list(self._db.list_job_log_entries(parent_key) or [])
            except Exception:
                logs = []
        return {
            "ok": True,
            "client": client,
            "jobs": jobs,
            "job_log": logs,
            "job_count": len(jobs),
            "requested_reference": requested if requested != client.get("name") else "",
            "resolved_client_name": client.get("name") or requested,
            "data_source": data.get("state", {}).get("source") or "supabase",
            "data_state": data.get("state") or {},
        }

    def _rows_all(self, table: str, limit: int = 1000) -> list:
        rows = []
        offset = 0
        while True:
            page = self._sb.rest("GET", table, params={
                "select": "*", "limit": str(limit), "offset": str(offset),
            }) or []
            if not isinstance(page, list):
                return rows
            rows.extend(page)
            if len(page) < limit:
                return rows
            offset += limit

    def _optional_rows(self, table: str, limit: int = 1000):
        try:
            return self._rows_all(table, limit), True
        except Exception as ex:
            text = str(ex).lower()
            if "pgrst205" in text or "could not find the table" in text:
                return [], False
            raise

    def _optional_table(self, table: str):
        """Check an optional feature table without downloading its history."""
        try:
            rows = self._sb.rest("GET", table, params={
                "select": "*", "limit": "1",
            }) or []
            return (rows if isinstance(rows, list) else []), True
        except Exception as ex:
            text = str(ex).lower()
            if "pgrst205" in text or "could not find the table" in text:
                return [], False
            raise

    def _local_environments(self) -> list:
        rows = []
        for job in self._db.iter_jobs() or []:
            for env in self._db.get_work_environment_states(job.get("canon_key")) or []:
                rows.append(env)
        return rows

    @staticmethod
    def _empty(mode: str, error: str, health: dict) -> dict:
        return {
            "ok": False, "error": error, "warnings": [], "clients": [],
            "state": {"mode": mode, "source": "supabase", "error": error,
                      "signed_in": bool(health.get("signed_in")),
                      "user": health.get("user")},
            "_jobs_by_id": {}, "_jobs_by_key": {}, "_aliases": {},
            "_children_by_card": {}, "_children_by_name": {},
            "_accounts_by_key": {}, "_reference_to_account": {},
        }

    def _shape(self, jobs, children, aliases, environments, crm_clients,
               crm_claims, *, source: str) -> dict:
        by_key = {str(row.get("canon_key") or ""): dict(row) for row in jobs
                  if row.get("canon_key")}
        by_id = {str(row.get("job_id") or ""): row for row in by_key.values()
                 if row.get("job_id")}
        env_by_job = {}
        for row in environments:
            job_id = str(row.get("job_id") or "")
            division = _division(row.get("work_environment"))
            if job_id and division:
                env_by_job.setdefault(job_id, []).append({**row, "division": division})
        for row in by_key.values():
            row["_divisions"] = []
            row["_division_states"] = env_by_job.get(str(row.get("job_id") or ""), [])
            for env in row["_division_states"]:
                if env["division"] not in row["_divisions"]:
                    row["_divisions"].append(env["division"])

        children_by_parent = {}
        children_by_card = {}
        children_by_name = {}
        for raw in children:
            child = dict(raw)
            parent = str(child.get("parent_canon") or "")
            if parent:
                children_by_parent.setdefault(parent, []).append(child)
            card = _card_key(child.get("trello_card"))
            if card:
                children_by_card[card] = child
            name_key = canon_key(child.get("name") or "")
            if name_key and name_key not in children_by_name:
                children_by_name[name_key] = child

        alias_map = {}
        for row in aliases:
            alias = canon_key(row.get("alias") or row.get("alias_canon") or "")
            target = str(row.get("canon_key") or "")
            if alias and target:
                alias_map[alias] = target

        claim_by_id = {str(row.get("claim_id") or ""): row for row in crm_claims
                       if row.get("claim_id")}
        claims_by_client = {}
        for row in crm_claims:
            claims_by_client.setdefault(str(row.get("client_id") or ""), []).append(row)
        jobs_by_client = {}
        for row in by_key.values():
            client_id = str(row.get("client_id") or "")
            if client_id:
                jobs_by_client.setdefault(client_id, []).append(row)

        accounts = {}
        reference_to_account = {}
        if crm_clients:
            for raw in crm_clients:
                client_id = str(raw.get("client_id") or "")
                related = jobs_by_client.get(client_id, [])
                payloads = [self._job_payload(
                    row, claim_by_id.get(str(row.get("claim_id") or "")),
                    row.get("display_name") or "Job") for row in related]
                related_job_claims = {str(row.get("claim_id") or "") for row in related}
                for claim in claims_by_client.get(client_id, []):
                    if str(claim.get("claim_id") or "") not in related_job_claims:
                        payloads.append(self._claim_payload(claim))
                name = str(raw.get("display_name") or "Client")
                account_key = f"client:{client_id}"
                account = {
                    "key": account_key, "client_id": client_id, "name": name,
                    "folder": "", "folder_exists": False,
                    "phone": raw.get("phone") or "", "email": raw.get("email") or "",
                    "address": self._address(raw.get("address_json")),
                    "franchise": raw.get("department") or "",
                    "source": "supabase_crm", "_jobs": payloads,
                }
                accounts[account_key] = account
                reference_to_account[name.casefold()] = account_key
                reference_to_account[canon_key(name)] = account_key
                for row in related:
                    row["_account_key"] = account_key
                    reference_to_account[row.get("canon_key") or ""] = account_key

        # v9 rows without a v11 client remain first-class shared records.  This
        # is also the whole model until migration 011 is installed.
        for row_key, row in by_key.items():
            if row.get("_account_key"):
                continue
            kids = children_by_parent.get(row_key, [])
            name = self._legacy_account_name(row, kids)
            account_key = f"job:{row_key}"
            payloads = ([self._child_payload(child, row) for child in kids]
                        if kids else [self._job_payload(
                            row, None, row.get("display_name") or name)])
            folder = self._account_folder(kids)
            account = {
                "key": row_key, "job_id": row.get("job_id") or "", "name": name,
                "folder": folder, "folder_exists": bool(folder and os.path.isdir(folder)),
                "phone": row.get("phone") or "", "email": row.get("email") or "",
                "address": row.get("address") or "",
                "franchise": row.get("department") or "",
                "source": source + "_job_index", "_jobs": payloads,
            }
            accounts[account_key] = account
            row["_account_key"] = account_key
            for ref in (name, row.get("display_name"), row_key):
                if ref:
                    reference_to_account[str(ref).casefold()] = account_key
                    reference_to_account[canon_key(ref)] = account_key
            for child in kids:
                child_name = str(child.get("name") or "")
                if child_name:
                    reference_to_account[child_name.casefold()] = account_key
                    reference_to_account[canon_key(child_name)] = account_key

        for alias, target in alias_map.items():
            row = by_key.get(target)
            if row and row.get("_account_key"):
                reference_to_account[alias] = row["_account_key"]

        directory = []
        for account in accounts.values():
            jobs_payload = account.get("_jobs") or []
            divisions = []
            for job in jobs_payload:
                for division in job.get("divisions") or []:
                    if division not in divisions:
                        divisions.append(division)
            directory.append({
                "name": account.get("name") or "Client",
                "path": account.get("folder") or "",
                "job_count": len(jobs_payload), "divisions": divisions,
                "has_children": len(jobs_payload) > 1,
                "source": account.get("source") or source,
            })
        directory.sort(key=lambda item: item["name"].casefold())
        return {
            "clients": directory, "_jobs_by_id": by_id,
            "_jobs_by_key": by_key, "_aliases": alias_map,
            "_children_by_card": children_by_card,
            "_children_by_name": children_by_name,
            "_accounts_by_key": accounts,
            "_reference_to_account": reference_to_account,
        }

    @staticmethod
    def _legacy_account_name(row: dict, children: list[dict]) -> str:
        display = str(row.get("display_name") or row.get("canon_key") or "Client").strip()
        management = re.split(r"\s*-\s*\(", display, maxsplit=1)
        if children and len(management) > 1 and management[0].strip():
            return management[0].strip()
        # The compatibility key deliberately strips carrier/date suffixes
        # from ordinary residential names.  When it is a clean prefix, use
        # that identity for the account and retain the full title on the job.
        key = str(row.get("canon_key") or "").strip()
        if (key and "(" not in key and display.casefold().startswith(key.casefold())
                and len(display) > len(key)):
            return key.title()
        return display

    @staticmethod
    def _account_folder(children: list[dict]) -> str:
        paths = [str(row.get("folder_path") or "") for row in children
                 if row.get("folder_path")]
        return os.path.dirname(paths[0]) if paths else ""

    @staticmethod
    def _address(value) -> str:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return value
        if not isinstance(value, dict):
            return ""
        return ", ".join(str(value.get(key) or "").strip() for key in
                         ("line1", "line2", "city", "state", "postal_code")
                         if str(value.get(key) or "").strip())

    @staticmethod
    def _claim_payload(claim: dict) -> dict:
        return {
            "key": claim.get("claim_id") or "", "name": "Claim",
            "path": "", "folder_exists": False, "divisions": [],
            "kind": "claim", "claim_number": claim.get("claim_number") or "",
            "carrier": claim.get("carrier") or "",
            "status": claim.get("status") or "", "date_received": _display_date(claim.get("date_received")),
            "date_of_loss": _display_date(claim.get("loss_date")),
            "cause_of_loss": claim.get("loss_type") or "", "property": "",
        }

    def _job_payload(self, row: dict, claim: dict | None, name: str) -> dict:
        claim = claim or {}
        return {
            "key": row.get("job_id") or row.get("canon_key") or "",
            "job_id": row.get("job_id") or "", "name": name,
            "path": "", "folder_exists": False,
            "divisions": list(row.get("_divisions") or []),
            "division_states": list(row.get("_division_states") or []),
            "kind": "claim", "claim_number": claim.get("claim_number") or row.get("claim_number") or "",
            "carrier": claim.get("carrier") or row.get("carrier") or "",
            "status": row.get("lifecycle_stage") or claim.get("status") or row.get("status") or "",
            "date_received": _display_date(claim.get("date_received") or row.get("date_received")),
            "date_of_loss": _display_date(claim.get("loss_date") or row.get("date_of_loss")),
            "cause_of_loss": claim.get("loss_type") or row.get("loss_type") or "",
            "deductible": row.get("deductible") or "",
            "adjuster_name": row.get("adjuster_name") or "",
            "adjuster_email": row.get("adjuster_email") or "",
            "insured_name": row.get("insured_name") or "", "property": row.get("property") or "",
        }

    def _child_payload(self, child: dict, parent: dict) -> dict:
        md = _metadata(child)
        return {
            "key": f"child:{child.get('id')}", "name": child.get("name") or "Job",
            "path": child.get("folder_path") or "",
            "folder_exists": bool(child.get("folder_path") and os.path.isdir(child.get("folder_path"))),
            "divisions": list(parent.get("_divisions") or []),
            "division_states": list(parent.get("_division_states") or []),
            "kind": child.get("kind") or "job",
            "claim_number": md.get("claim_number") or "",
            "carrier": md.get("carrier") or "",
            "status": parent.get("lifecycle_stage") or parent.get("status") or "",
            "date_received": _display_date(child.get("claim_date") or md.get("date_received")),
            "date_of_loss": _display_date(md.get("date_of_loss")),
            "cause_of_loss": md.get("loss_type") or "",
            "deductible": md.get("deductible") or "",
            "adjuster_name": md.get("adjuster_name") or "",
            "adjuster_email": md.get("adjuster_email") or "",
            "insured_name": md.get("insured_name") or "",
            "property": child.get("property") or "", "unit": child.get("unit") or "",
            "trello_card": child.get("trello_card") or "",
            "companycam": child.get("companycam") or "",
        }
