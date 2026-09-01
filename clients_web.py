"""Clients workspace.

Client identity and history live here.  The existing Daily Run / Job Audit
module remains focused on today's operational audit and is intentionally not
used as the client page implementation.
"""
from __future__ import annotations

import os


class Api:
    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    @staticmethod
    def _divisions(path: str) -> list[str]:
        if not path or not os.path.isdir(path):
            return []
        import job_folders
        found = []
        for name in job_folders.shells_at(path):
            key = str(name or "").upper()
            if key in {"EMS", "CONTENTS", "RECON"} and key not in found:
                found.append(key)
        return found

    def list_clients(self, query: str = "", division: str = "all",
                     limit: int = 250) -> dict:
        """Return a light client directory from the configured OD root."""
        try:
            import job_folders
            rows = job_folders.search_clients(query or "", limit=max(1, int(limit or 250)))
            # A job-card deep link carries the card title, not merely the
            # account name. Management work commonly uses
            #   PCM - (Kellogg Terrace) - Cruz, Sarah 8/28
            # where PCM is the client and the rest identifies one job. If
            # the complete title is not a top-level OD client, retry its
            # leading segments against real top-level folders. The folder
            # match is the proof; splitting alone never invents a parent.
            if not rows and query:
                pieces = [part.strip() for part in str(query).split(" - ")]
                for end in range(len(pieces) - 1, 0, -1):
                    hint = " - ".join(pieces[:end])
                    candidates = job_folders.search_clients(hint, limit=max(1, int(limit or 250)))
                    normalized_hint = " ".join(hint.casefold().split())
                    exact = [row for row in candidates if
                             " ".join(str(row.get("name") or "").casefold().split())
                             == normalized_hint]
                    if exact:
                        rows = exact
                        break
            wanted = (division or "all").strip().upper()
            clients = []
            for row in rows:
                path = row.get("path") or ""
                divisions = self._divisions(path)
                child_names = row.get("children") or []
                child_divisions = set()
                for name in child_names:
                    child_divisions.update(self._divisions(os.path.join(path, name)))
                all_divisions = divisions + sorted(child_divisions - set(divisions))
                if wanted not in {"", "ALL"} and wanted not in all_divisions:
                    continue
                clients.append({
                    "name": row.get("name") or "Client",
                    "path": path,
                    "job_count": max(1 if divisions else 0, 0) + len(child_names),
                    "divisions": all_divisions,
                    "has_children": bool(child_names),
                })
            return {"ok": True, "clients": clients, "count": len(clients)}
        except Exception as ex:
            return {"ok": False, "clients": [],
                    "error": f"{type(ex).__name__}: {ex}"}

    def client_account(self, client: str) -> dict:
        """Return one Client -> Job -> Division hierarchy.

        OD is the hierarchy authority. The shared/local job index contributes
        identity and claim metadata where it has a matching record.
        """
        client = (client or "").strip()
        if not client:
            return {"ok": False, "error": "Choose a client first."}
        try:
            import ems_db
            import ems_db_common
            import job_folders
            import persistence

            # The directory must remain usable offline and during an auth
            # refresh race. OD owns hierarchy, so cloud metadata enriches
            # the page but never gates it.
            try:
                record = ems_db.find_job_by_name(client) or {}
            except Exception:
                record = {}
            canonical = record.get("canon_key") or ems_db_common.canon_key(client)
            display = record.get("display_name") or client
            folder = persistence.get_folder_path(client) or ""
            if not folder or not os.path.isdir(folder):
                folder = job_folders.find_client_folder(client) or folder

            jobs = []
            root_divisions = self._divisions(folder)
            if root_divisions:
                jobs.append(self._job_payload(
                    key=canonical or display.casefold(), name="Original claim",
                    path=folder, divisions=root_divisions, record=record,
                    kind="claim"))

            seen = set()
            if folder and os.path.isdir(folder):
                for child_name in job_folders.list_children(folder):
                    child_path = os.path.join(folder, child_name)
                    if not job_folders.is_child_job_folder(child_path, child_name):
                        continue
                    seen.add(child_name.casefold())
                    kind, _ = ems_db_common.classify_child(child_name)
                    jobs.append(self._job_payload(
                        key=f"{canonical}::{child_name}", name=child_name,
                        path=child_path, divisions=self._divisions(child_path),
                        record={}, kind=kind or "job"))

            try:
                indexed_children = ems_db.children_of(canonical) or [] if canonical else []
            except Exception:
                indexed_children = []
            if canonical:
                for child in indexed_children:
                    name = child.get("name") or "Job"
                    if name.casefold() in seen:
                        continue
                    path = child.get("folder_path") or ""
                    jobs.append(self._job_payload(
                        key=child.get("id") or f"{canonical}::{name}", name=name,
                        path=path, divisions=self._divisions(path), record=child,
                        kind=child.get("kind") or "job"))

            if not jobs:
                jobs.append(self._job_payload(
                    key=canonical or display.casefold(), name="Current job",
                    path=folder, divisions=[], record=record, kind="claim"))

            try:
                aliases = list(ems_db.get_aliases(canonical) or []) if canonical else []
            except Exception:
                aliases = []
            return {
                "ok": True,
                "client": {
                    "key": canonical,
                    "name": display,
                    "folder": folder,
                    "folder_exists": bool(folder and os.path.isdir(folder)),
                    "phone": record.get("phone") or "",
                    "email": record.get("email") or "",
                    "address": record.get("address") or "",
                    "franchise": record.get("department") or "",
                    "aliases": aliases,
                },
                "jobs": jobs,
                "job_count": len(jobs),
            }
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @staticmethod
    def _job_payload(*, key, name, path, divisions, record, kind):
        return {
            "key": key,
            "name": name,
            "path": path or "",
            "folder_exists": bool(path and os.path.isdir(path)),
            "divisions": divisions or [],
            "kind": kind or "job",
            "claim_number": record.get("claim_number") or "",
            "carrier": record.get("carrier") or "",
            "status": record.get("status") or "",
        }

    def open_folder(self, path: str) -> dict:
        path = (path or "").strip()
        if not path or not os.path.isdir(path):
            return {"ok": False, "error": "That folder is not available on this PC."}
        try:
            os.startfile(path)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
