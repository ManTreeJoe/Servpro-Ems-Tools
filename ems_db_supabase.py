"""Job index — shared Postgres backend over Supabase's PostgREST API.

Same public surface as `ems_db_sqlite`; `ems_db` picks between them. All
identity logic (canon_key, link normalization, the department→root map,
the child classifier) comes from `ems_db_common`, so the two backends
cannot disagree about what a job IS.

Transport is `supabase_client`: plain HTTPS via urllib, authenticated as
the signed-in user so Row-Level Security applies. There is no database
password anywhere — the publishable key identifies the project and grants
nothing on its own.

Shared lifecycle support
------------------------
The `lifecycle_*` functions use the shared Postgres tables so Trello stages
and transition history remain consistent across trial computers. Full
database export/import remains a local SQLite maintenance operation and
raises a clear error on this backend.

Round-trip discipline
---------------------
Every call here is network latency, so anything the UI does per row must
be batched — `card_display_names_for` is the reason the audit render was
rewritten from ~600 queries to one. When adding a function, assume 60ms
per request and design accordingly.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import supabase_client as _sb
from ems_db_common import (            # noqa: F401 — re-exported as API
    _UNIT_DETECT_PATTERNS, detect_property_and_unit, canon_key,
    LINK_FOLDER, LINK_TRELLO, LINK_COMPANYCAM, _STRONG_LINK_TYPES,
    is_strong_link,
    _norm_link, invalidate_department_cache, department_for_path,
    split_department_path, rebase_department_path,
    portable_folder_path, resolve_portable_folder_path,
    folder_storage_candidates,
    CHILD_CLAIM, CHILD_UNIT, CHILD_SUBJOB, classify_child, _now_iso,
    EVENT_CREATED, EVENT_RENAMED, EVENT_SNAPSHOT_REVISION, is_material_rename,
    alias_probe_token, truncation_alias_is_ambiguous, dedupe_child_name,
)

SCHEMA_VERSION = 10


class DepartmentConflict(Exception):
    """Raised when an operation would tie one franchise's data to another
    franchise's job. Mirrors the SQLite backend — always a data question
    for a human."""


def _unsupported(name):
    raise NotImplementedError(
        f"{name}() is a bulk/maintenance operation and stays on the local "
        f"SQLite index — set ems_db_backend to 'sqlite' to run it.")


# ── low-level helpers ───────────────────────────────────────────────────

_PAGE = 1000

# Deterministic paging needs an ORDER BY. PostgREST guarantees no ordering
# across limit/offset pages, so without one a row can repeat on page 2
# while another vanishes entirely.
_ORDER_BY = {
    "jobs":                  "canon_key",
    "job_aliases":           "canon_key,alias_canon",
    "job_links":             "canon_key,link_type,link_value",
    "job_children":          "id",
    "job_events":            "id",
    "job_lifecycle":         "card_id",
    "job_stage_transitions": "id",
    "meta":                  "key",
    "app_user_departments":  "user_id,department",
    "crm_job_departments":   "job_id,work_environment",
    "crm_job_relationships": "job_id,related_job_id,relationship_type",
    "crm_job_log_entries":  "job_id,work_date,created_at,entry_id",
    "crm_job_log_revisions": "entry_id,revision_id",
}


def _rows(table, **params):
    """GET rows, following pagination to the end.

    Supabase caps a select at `db-max-rows` (1000) and reports the cap
    only in the Content-Range header, which we don't surface. An unpaged
    read of job_lifecycle — 3175 rows live — therefore returned the first
    1000 and looked complete, silently hiding two thirds of the pipeline
    from every lifecycle query.

    A caller passing its own `limit` wants a bounded slice (see `_one`),
    so that is honoured as-is and never paged.
    """
    if "limit" in params:
        out = _sb.rest("GET", table, params=params)
        return out if isinstance(out, list) else []

    params.setdefault("order", _ORDER_BY.get(table, "id"))
    out, offset = [], 0
    while True:
        got = _sb.rest("GET", table, params={**params, "limit": str(_PAGE),
                                             "offset": str(offset)})
        if not isinstance(got, list):
            return out
        out.extend(got)
        if len(got) < _PAGE:
            return out
        offset += _PAGE


def _one(table, **params):
    params.setdefault("limit", "1")
    rows = _rows(table, **params)
    return rows[0] if rows else None


def _in(values):
    """PostgREST `in.(a,b,c)` — values quoted so commas/parens survive."""
    esc = [str(v).replace('"', '\\"') for v in values]
    return "in.(" + ",".join(f'"{v}"' for v in esc) + ")"


def _job(row):
    """Shape a jobs row like the SQLite backend does (metadata parsed)."""
    if not row:
        return None
    d = dict(row)
    md = d.pop("metadata_json", None)
    if md:
        try:
            d["metadata"] = json.loads(md)
        except (TypeError, ValueError):
            d["metadata"] = {}
    return d


# ── jobs ────────────────────────────────────────────────────────────────

def upsert_job(*, display_name: str, claim_number: str = "",
               carrier: str = "", loss_type: str = "", year=None,
               status: str = "", date_received: str = "",
               department: str = "", metadata: dict | None = None,
               **crm) -> str:
    """Insert or update, with the SQLite backend's partial-update rule: a
    blank value never overwrites an existing non-blank one.

    v6 CRM fields come through **crm and share the sqlite column list, so
    the two backends cannot drift on which fields exist."""
    from ems_db_sqlite import CRM_COLUMNS, _TEXT_COLUMNS
    unknown = set(crm) - set(CRM_COLUMNS)
    if unknown:
        raise TypeError(
            f"upsert_job() got unexpected keyword(s): {sorted(unknown)}")
    supplied = dict(crm)
    supplied.update({
        "claim_number": claim_number, "carrier": carrier,
        "loss_type": loss_type, "status": status,
        "date_received": date_received,
    })

    key = canon_key(display_name)
    if not key:
        raise ValueError("display_name must canonicalize to a non-empty key")
    now = _now_iso()
    existing = _one("jobs", canon_key=f"eq.{key}", select="*")
    md_json = json.dumps(metadata) if metadata else None
    if existing is None:
        body = {
            "canon_key": key, "display_name": display_name, "year": year,
            "first_seen_at": now, "last_seen_at": now,
            "metadata_json": md_json,
            "department": (department or "").strip() or None,
        }
        for col in _TEXT_COLUMNS:
            body[col] = supplied.get(col) or None
        _sb.rest("POST", "jobs", body=body,
                 prefer="resolution=merge-duplicates")
        # Start the same append-only lifecycle used by the local backend.
        # Best-effort so an event logging problem cannot hide the job itself.
        try:
            log_event(key, EVENT_CREATED)
        except Exception:
            pass
        return key
    # Captured before the PATCH overwrites it — see the SQLite backend.
    renamed_from = (existing.get("display_name")
                    if is_material_rename(existing.get("display_name"),
                                          display_name) else "")
    patch = {
        "display_name":  display_name or existing.get("display_name"),
        "year":          year if year is not None else existing.get("year"),
        "last_seen_at":  now,
        "metadata_json": md_json or existing.get("metadata_json"),
        "department":    ((department or "").strip()
                          or existing.get("department") or None),
    }
    for col in _TEXT_COLUMNS:
        patch[col] = supplied.get(col) or existing.get(col)
    _sb.rest("PATCH", "jobs", params={"canon_key": f"eq.{key}"}, body=patch)
    if renamed_from:
        try:
            add_alias(key, renamed_from, source="rename")
        except Exception:
            pass
        try:
            log_event(key, EVENT_RENAMED,
                      payload={"from": renamed_from, "to": display_name})
        except Exception:
            pass
    return key


def get_job(canon_key_value: str):
    if not canon_key_value:
        return None
    return _job(_one("jobs", canon_key=f"eq.{canon_key_value}", select="*"))


def get_job_by_id(job_id: str):
    if not job_id:
        return None
    return _job(_one("jobs", job_id=f"eq.{job_id}", select="*"))


def set_master_job_state(canon_key_value: str, *, lifecycle_stage: str = "",
                         job_type: str = "", priority: str = "",
                         source: str = "manual") -> dict:
    from ems_db_sqlite import (CRM_JOB_TYPES, CRM_LIFECYCLE_STAGES,
                               CRM_PRIORITIES)
    lifecycle_stage = (lifecycle_stage or "").strip().lower()
    job_type = (job_type or "").strip().lower()
    priority = (priority or "").strip().lower()
    source = (source or "manual").strip().lower()
    if lifecycle_stage and lifecycle_stage not in CRM_LIFECYCLE_STAGES:
        raise ValueError(f"unknown lifecycle stage: {lifecycle_stage}")
    if job_type and job_type not in CRM_JOB_TYPES:
        raise ValueError(f"unknown job type: {job_type}")
    if priority and priority not in CRM_PRIORITIES:
        raise ValueError(f"unknown priority: {priority}")
    if source not in ("manual", "trello", "migration", "system"):
        raise ValueError(f"unknown lifecycle source: {source}")
    current = get_job(canon_key_value)
    if not current:
        raise KeyError(canon_key_value)
    patch = {}
    stage_change = None
    if lifecycle_stage and lifecycle_stage != current.get("lifecycle_stage"):
        stage_change = (current.get("lifecycle_stage") or "", lifecycle_stage)
        now = _now_iso()
        patch.update(lifecycle_stage=lifecycle_stage, stage_entered_at=now,
                     closed_at=(now if lifecycle_stage == "closed" else None),
                     lifecycle_source=source)
    if job_type:
        patch["job_type"] = job_type
    if priority:
        patch["priority"] = priority
    if patch:
        _sb.rest("PATCH", "jobs",
                 params={"canon_key": f"eq.{canon_key_value}"}, body=patch)
    if stage_change:
        log_event(canon_key_value, "crm_stage_changed", payload={
            "from_stage": stage_change[0], "to_stage": stage_change[1],
            "source": source})
    return get_master_job(canon_key_value)


def set_work_environment_state(canon_key_value: str, work_environment: str,
                               *, stage: str = "", status: str = "",
                               owner: str = "") -> dict:
    from ems_db_sqlite import CRM_WORK_ENVIRONMENTS
    env = (work_environment or "").strip()
    env = next((v for v in CRM_WORK_ENVIRONMENTS
                if v.lower() == env.lower()), "")
    if not env:
        raise ValueError(f"unknown work environment: {work_environment}")
    job = get_job(canon_key_value)
    if not job:
        raise KeyError(canon_key_value)
    old = _one("crm_job_departments", job_id=f"eq.{job['job_id']}",
               work_environment=f"eq.{env}", select="*")
    now = _now_iso()
    changed_stage = not old or (stage and stage != old.get("stage"))
    previous_stage = (old or {}).get("stage") or ""
    body = {
        "job_id": job["job_id"], "work_environment": env,
        "stage": stage or (old or {}).get("stage"),
        "status": status or (old or {}).get("status"),
        "owner": owner or (old or {}).get("owner"),
        "stage_entered_at": now if changed_stage else (old or {}).get("stage_entered_at"),
        "started_at": (old or {}).get("started_at") or now,
        "completed_at": (now if (stage or "").lower() == "closed"
                         else (old or {}).get("completed_at")),
        "updated_at": now,
    }
    rows = _sb.rest("POST", "crm_job_departments", body=body,
                    prefer="resolution=merge-duplicates,return=representation")
    if changed_stage and stage:
        log_event(canon_key_value, "crm_department_stage_changed", payload={
            "work_environment": env, "from_stage": previous_stage,
            "to_stage": stage, "owner": owner})
    return (rows or [body])[0]


def get_work_environment_states(canon_key_value: str) -> list:
    job = get_job(canon_key_value)
    if not job:
        return []
    rows = _rows("crm_job_departments", job_id=f"eq.{job['job_id']}",
                 select="*")
    rank = {"EMS": 1, "Contents": 2, "Recon": 3}
    return sorted(rows, key=lambda r: rank.get(r.get("work_environment"), 4))


def get_master_job(canon_key_value: str):
    job = get_job(canon_key_value)
    if not job:
        return None
    job["work_environments"] = get_work_environment_states(canon_key_value)
    job["relationships"] = get_job_relationships(canon_key_value)
    return job


_JOB_LOG_STATUSES = {"scheduled", "completed", "rescheduled", "cancelled",
                     "skipped", "needs_review"}


def _job_log_schema_missing(ex) -> bool:
    body = str(getattr(ex, "body", "") or ex)
    return (getattr(ex, "status", None) == 404 and "PGRST205" in body
            and ("crm_job_log_entries" in body
                 or "crm_job_log_revisions" in body))


def _event_job_log_rows(canon_key_value: str) -> list:
    latest = {}
    for event in reversed(list_events(canon_key_value,
                                      "crm_job_log_revision", limit=1000)):
        payload = event.get("payload") or {}
        after = payload.get("after") or {}
        entry_id = after.get("entry_id") or payload.get("entry_id")
        if entry_id:
            latest[entry_id] = after
    return sorted(latest.values(), key=lambda row: (
        row.get("work_date") or "", row.get("created_at") or "",
        row.get("entry_id") or ""))


def _event_job_log_history(entry_id: str) -> list:
    rows = _rows("job_events", event_type="eq.crm_job_log_revision",
                 select="id,event_at,payload_json,actor", order="id.desc")
    out = []
    for row in rows:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        if payload.get("entry_id") != entry_id:
            continue
        out.append({"revision_id": row.get("id"), "entry_id": entry_id,
                    "changed_at": row.get("event_at"),
                    "changed_by": row.get("actor") or "",
                    "before_json": json.dumps(payload.get("before")) if payload.get("before") else None,
                    "after_json": json.dumps(payload.get("after") or {})})
    return out


def list_job_log_entries(canon_key_value: str) -> list:
    job = get_job(canon_key_value)
    if not job:
        return []
    try:
        return _rows("crm_job_log_entries", job_id=f"eq.{job['job_id']}",
                     select="*", order="work_date,created_at,entry_id")
    except Exception as ex:
        if not _job_log_schema_missing(ex):
            raise
        return _event_job_log_rows(canon_key_value)


def save_job_log_entry(canon_key_value: str, entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("job log entry must be an object")
    job = get_job(canon_key_value)
    if not job:
        raise KeyError(canon_key_value)
    work_date = str(entry.get("work_date") or "").strip()
    work_type = str(entry.get("work_type") or "").strip()
    status = str(entry.get("status") or "completed").strip().lower()
    if not work_date or not work_type:
        raise ValueError("work date and work type are required")
    if status not in _JOB_LOG_STATUSES:
        raise ValueError(f"unknown job log status: {status}")
    source = str(entry.get("source") or "pc").strip().lower() or "pc"
    source_id = str(entry.get("source_id") or "").strip()
    old = None
    entry_id = str(entry.get("entry_id") or "").strip()
    use_events = False
    try:
        if entry_id:
            old = _one("crm_job_log_entries", entry_id=f"eq.{entry_id}", select="*")
        if old is None and source_id:
            old = _one("crm_job_log_entries", job_id=f"eq.{job['job_id']}",
                       source=f"eq.{source}", source_id=f"eq.{source_id}", select="*")
    except Exception as ex:
        if not _job_log_schema_missing(ex):
            raise
        use_events = True
        existing = _event_job_log_rows(canon_key_value)
        old = next((row for row in existing if
                    (entry_id and row.get("entry_id") == entry_id) or
                    (source_id and row.get("source") == source and
                     row.get("source_id") == source_id)), None)
    entry_id = (old or {}).get("entry_id") or entry_id or str(uuid.uuid4())
    now = _now_iso()
    body = {
        "entry_id": entry_id, "job_id": job["job_id"],
        "work_date": work_date, "work_type": work_type, "status": status,
        "technicians": str(entry.get("technicians") or "").strip() or None,
        "note": str(entry.get("note") or "").strip() or None,
        "equipment": str(entry.get("equipment") or "").strip() or None,
        "source": source, "source_id": source_id or None,
        "trello_comment_id": str(entry.get("trello_comment_id") or "").strip() or None,
        "created_at": (old or {}).get("created_at") or now,
        "updated_at": now,
        "updated_by": str(entry.get("updated_by") or "").strip() or None,
    }
    if use_events:
        saved = body
        log_event(canon_key_value, "crm_job_log_revision", payload={
            "entry_id": entry_id, "before": old, "after": saved})
        return saved
    try:
        rows = _sb.rest("POST", "crm_job_log_entries", body=body,
                        prefer="resolution=merge-duplicates,return=representation")
        saved = (rows or [body])[0]
        _sb.rest("POST", "crm_job_log_revisions", body={
            "entry_id": entry_id, "changed_at": now,
            "changed_by": body["updated_by"], "before_json": old,
            "after_json": saved,
        })
    except Exception as ex:
        if not _job_log_schema_missing(ex):
            raise
        saved = body
        log_event(canon_key_value, "crm_job_log_revision", payload={
            "entry_id": entry_id, "before": old, "after": saved})
    return saved


def job_log_history(entry_id: str) -> list:
    if not entry_id:
        return []
    try:
        return _rows("crm_job_log_revisions", entry_id=f"eq.{entry_id}",
                     select="*", order="revision_id.desc")
    except Exception as ex:
        if not _job_log_schema_missing(ex):
            raise
        return _event_job_log_history(entry_id)


def delete_job_log_entry(canon_key_value: str, entry_id: str) -> bool:
    job = get_job(canon_key_value)
    if not job or not entry_id:
        return False
    try:
        old = _one("crm_job_log_entries", entry_id=f"eq.{entry_id}",
                   job_id=f"eq.{job['job_id']}", select="entry_id")
        if not old:
            return False
        _sb.rest("DELETE", "crm_job_log_revisions",
                 params={"entry_id": f"eq.{entry_id}"})
        _sb.rest("DELETE", "crm_job_log_entries", params={
            "entry_id": f"eq.{entry_id}", "job_id": f"eq.{job['job_id']}"})
        return True
    except Exception as ex:
        if not _job_log_schema_missing(ex):
            raise
        # Legacy event-backed rows cannot be physically removed safely.
        raise RuntimeError("Shared Job Log update is required before entries can be deleted")


def relate_jobs(canon_key_value: str, related_canon_key: str,
                relationship_type: str, *, created_by: str = "") -> bool:
    from ems_db_sqlite import CRM_RELATIONSHIP_TYPES
    relation = (relationship_type or "").strip().lower()
    if relation not in CRM_RELATIONSHIP_TYPES:
        raise ValueError(f"unknown relationship type: {relationship_type}")
    left, right = get_job(canon_key_value), get_job(related_canon_key)
    if not left or not right:
        raise KeyError(canon_key_value if not left else related_canon_key)
    if left["job_id"] == right["job_id"]:
        raise ValueError("a job cannot be related to itself")
    existing = _one(
        "crm_job_relationships", job_id=f"eq.{left['job_id']}",
        related_job_id=f"eq.{right['job_id']}",
        relationship_type=f"eq.{relation}", select="job_id")
    if existing:
        return False
    _sb.rest("POST", "crm_job_relationships", body={
        "job_id": left["job_id"], "related_job_id": right["job_id"],
        "relationship_type": relation, "created_at": _now_iso(),
        "created_by": (created_by or "").strip() or None,
    })
    return True


def remove_job_relationship(canon_key_value: str, related_canon_key: str,
                            relationship_type: str) -> bool:
    left, right = get_job(canon_key_value), get_job(related_canon_key)
    if not left or not right:
        return False
    relation = (relationship_type or "").strip().lower()
    existing = _one(
        "crm_job_relationships", job_id=f"eq.{left['job_id']}",
        related_job_id=f"eq.{right['job_id']}",
        relationship_type=f"eq.{relation}", select="job_id")
    if not existing:
        return False
    _sb.rest("DELETE", "crm_job_relationships", params={
        "job_id": f"eq.{left['job_id']}",
        "related_job_id": f"eq.{right['job_id']}",
        "relationship_type": f"eq.{relation}",
    })
    return True


def get_job_relationships(canon_key_value: str) -> list:
    job = get_job(canon_key_value)
    if not job:
        return []
    rows = _rows("crm_job_relationships", job_id=f"eq.{job['job_id']}",
                 select="*")
    out = []
    for row in rows:
        related = get_job_by_id(row.get("related_job_id")) or {}
        item = dict(row)
        item["related_canon_key"] = related.get("canon_key") or ""
        item["related_display_name"] = related.get("display_name") or ""
        out.append(item)
    return sorted(out, key=lambda r: (
        r.get("relationship_type") or "", r.get("related_display_name") or ""))


def iter_jobs() -> list:
    # Newest-seen first, matching the SQLite contract. Ordering by
    # canon_key here instead returned the list alphabetically, which no
    # caller expects and the conformance suite could not see because it
    # compares row SETS, not sequence. canon_key breaks ties so paging
    # stays deterministic when several jobs share a last_seen_at.
    return [_job(r) for r in _rows("jobs", select="*",
                                   order="last_seen_at.desc,canon_key.asc")]


def find_jobs_by_status(status: str) -> list:
    if not status:
        return []
    return [_job(r) for r in _rows("jobs", select="*",
                                   status=f"eq.{status}")]


def find_job_by_name(name: str, *, department: str = ""):
    """Direct canon_key hit first, then alias — the same precedence as the
    SQLite backend. Two round trips at worst; batch with
    `card_display_names_for` when resolving many names."""
    if not name:
        return None
    key = canon_key(name)
    if not key:
        return None
    row = _one("jobs", canon_key=f"eq.{key}", select="*")
    if row is None:
        a = _one("job_aliases", alias_canon=f"eq.{key}", select="canon_key")
        if a:
            row = _one("jobs", canon_key=f"eq.{a['canon_key']}", select="*")
            # An alias that TRUNCATES the job's name claims every sibling
            # — see truncation_alias_is_ambiguous. The guard has to be
            # here as well as in SQLite because THIS backend serves the
            # live reads; SQLite only answers when the server is
            # unreachable, so fixing it there alone fixed nothing.
            if row is not None:
                tok = alias_probe_token(key)
                if tok:
                    cands = [r.get("canon_key") for r in (_rows(
                        "jobs", canon_key=f"like.*{tok}*",
                        select="canon_key") or [])]
                    if truncation_alias_is_ambiguous(
                            key, row.get("canon_key"), cands):
                        return None
    if row is not None and (department or "").strip():
        have = (row.get("department") or "").strip()
        if have and have != department.strip():
            return None
    return _job(row)


def _is_primary_job_key(key: str) -> bool:
    return bool(key) and _one("jobs", canon_key=f"eq.{key}",
                              select="canon_key") is not None


# ── aliases ─────────────────────────────────────────────────────────────

def add_alias(canon_key_value: str, alias: str, *,
              source: str = "manual", force: bool = False) -> bool:
    """Mirror of the sqlite guard — an alias may only ever name ONE job.
    Refuses a second claimant so a fuzzy matcher's wrong guess can't
    silently overwrite an established mapping. Keep the two in step:
    whichever backend is active has to reject the same writes.
    `force=True` is for deliberate folding (merge_jobs / reconcile)."""
    if not (canon_key_value and alias):
        return False
    ac = canon_key(alias)
    if not ac or ac == canon_key_value:
        return False
    if not force:
        # Already another job's canon_key?
        other = _one("jobs", canon_key=f"eq.{ac}", select="canon_key")
        if other is not None and other.get("canon_key") != canon_key_value:
            return False
        # Already an alias of another job?
        for r in _rows("job_aliases", alias_canon=f"eq.{ac}",
                       select="canon_key", limit=5):
            if r.get("canon_key") != canon_key_value:
                return False
    _sb.rest("POST", "job_aliases", body={
        "canon_key": canon_key_value, "alias": alias, "alias_canon": ac,
        "source": source, "added_at": _now_iso(),
    }, prefer="resolution=merge-duplicates")
    return True


def get_aliases(canon_key_value: str) -> list:
    if not canon_key_value:
        return []
    return [r["alias"] for r in
            _rows("job_aliases", canon_key=f"eq.{canon_key_value}",
                  select="alias", order="added_at.asc")]


def name_history(canon_key_value: str) -> list:
    """Every recorded rename for a job, oldest first — see the SQLite twin."""
    if not canon_key_value:
        return []
    out = []
    for r in _rows("job_events", canon_key=f"eq.{canon_key_value}",
                   event_type=f"eq.{EVENT_RENAMED}",
                   select="event_at,payload_json", order="event_at.asc"):
        raw = r.get("payload_json")
        try:
            p = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            continue
        if p.get("from") or p.get("to"):
            out.append({"from": p.get("from") or "",
                        "to": p.get("to") or "",
                        "at": r.get("event_at")})
    return out


def all_aliases() -> list:
    """Every (canon_key, alias) pair in ONE request — see the SQLite twin.
    `_rows` pages, so this is complete even past the 1000-row cap."""
    return [{"canon_key": r.get("canon_key"), "alias": r.get("alias")}
            for r in _rows("job_aliases", select="canon_key,alias")]


# ── links ───────────────────────────────────────────────────────────────

def set_link(canon_key_value: str, link_type: str, link_value: str, *,
             metadata: dict | None = None, added_by: str = "") -> None:
    original_folder = link_value if link_type == LINK_FOLDER else ""
    if link_type == LINK_FOLDER:
        link_value = portable_folder_path(link_value)
    elif is_strong_link(link_type):
        link_value = _norm_link(link_type, link_value)
    if not (canon_key_value and link_type and link_value):
        return
    _sb.rest("POST", "job_links", body={
        "canon_key": canon_key_value, "link_type": link_type,
        "link_value": link_value, "added_at": _now_iso(),
        "added_by": added_by,
        "metadata_json": json.dumps(metadata) if metadata else None,
    }, prefer="resolution=merge-duplicates")
    # A folder pin is what says which franchise owns the job — same rule as
    # the SQLite backend. Fills a NULL only; never reassigns an owner.
    if link_type == LINK_FOLDER:
        dept = department_for_path(original_folder)
        if dept:
            _sb.rest("PATCH", "jobs",
                     params={"canon_key": f"eq.{canon_key_value}",
                             "department": "is.null"},
                     body={"department": dept})


def get_link(canon_key_value: str, link_type: str):
    if not (canon_key_value and link_type):
        return None
    r = _one("job_links", canon_key=f"eq.{canon_key_value}",
             link_type=f"eq.{link_type}", select="link_value",
             order="added_at.asc")
    value = r["link_value"] if r else None
    return resolve_portable_folder_path(value) if link_type == LINK_FOLDER else value


def get_links(canon_key_value: str, link_type: str = "") -> list:
    if not canon_key_value:
        return []
    p = {"canon_key": f"eq.{canon_key_value}", "select": "*",
         "order": "added_at.asc"}
    if link_type:
        p["link_type"] = f"eq.{link_type}"
    rows = _rows("job_links", **p)
    out = []
    for row in rows:
        item = dict(row)
        if item.get("link_type") == LINK_FOLDER:
            item["portable_value"] = item.get("link_value") or ""
            item["link_value"] = resolve_portable_folder_path(
                item.get("link_value") or "")
        out.append(item)
    return out


def remove_link(canon_key_value: str, link_type: str,
                link_value: str = "") -> None:
    if not (canon_key_value and link_type):
        return
    p = {"canon_key": f"eq.{canon_key_value}", "link_type": f"eq.{link_type}"}
    if not link_value:
        _sb.rest("DELETE", "job_links", params=p)
        return
    candidates = (folder_storage_candidates(link_value)
                  if link_type == LINK_FOLDER
                  else [_norm_link(link_type, link_value)])
    for candidate in candidates:
        _sb.rest("DELETE", "job_links", params={**p,
                 "link_value": f"eq.{candidate}"})


def find_job_by_link(link_type: str, link_value: str):
    candidates = (folder_storage_candidates(link_value)
                  if link_type == LINK_FOLDER
                  else [_norm_link(link_type, link_value)])
    if not (link_type and candidates):
        return None
    for candidate in candidates:
        l = _one("job_links", link_type=f"eq.{link_type}",
                 link_value=f"eq.{candidate}", select="canon_key",
                 order="added_at.asc")
        if l:
            return get_job(l["canon_key"])
    return None


def migrate_folder_links_portable(*, apply: bool = False) -> dict:
    """Preview/convert legacy absolute shared folder links.

    Run on a machine whose franchise roots are configured correctly (the
    original owner's machine is ideal). Rows outside those roots are reported
    unresolved and never changed. Conversion inserts the portable value first,
    then removes the old absolute value, so an interruption cannot lose a pin.
    """
    rows = _rows("job_links", link_type=f"eq.{LINK_FOLDER}", select="*")
    convertible, already, unresolved, converted = [], [], [], 0
    for row in rows:
        old = (row.get("link_value") or "").strip()
        new = portable_folder_path(old)
        item = {"canon_key": row.get("canon_key") or "",
                "old": old, "new": new}
        if old.lower().startswith("linguar-folder://"):
            already.append(item)
            continue
        if not new or new == old:
            unresolved.append(item)
            continue
        convertible.append(item)
        if not apply:
            continue
        body = dict(row)
        body["link_value"] = new
        _sb.rest("POST", "job_links", body=body,
                 prefer="resolution=merge-duplicates")
        _sb.rest("DELETE", "job_links", params={
            "canon_key": f"eq.{row.get('canon_key')}",
            "link_type": f"eq.{LINK_FOLDER}",
            "link_value": f"eq.{old}",
        })
        converted += 1
    return {"ok": True, "apply": bool(apply), "total": len(rows),
            "convertible": len(convertible), "already_portable": len(already),
            "unresolved": len(unresolved), "converted": converted,
            "preview": convertible[:20], "unresolved_rows": unresolved[:20]}


# ── identity resolution ─────────────────────────────────────────────────

def _department_conflict(job, incoming_dept):
    if not job or not incoming_dept:
        return False
    have = (job.get("department") or "").strip()
    return bool(have) and have != incoming_dept


def resolve_and_link(name: str = "", *, folder_path: str = "",
                     trello_card: str = "", companycam_project: str = "",
                     create: bool = False, source: str = "auto",
                     display_name: str = "",
                     strict_department: bool = True):
    """Mirror of the SQLite implementation — strong links are ground truth,
    the incoming spelling becomes an alias, and a cross-franchise match is
    rejected rather than linked."""
    name = (name or "").strip()
    strong = [(LINK_FOLDER, folder_path),
              (LINK_TRELLO, trello_card),
              (LINK_COMPANYCAM, companycam_project)]
    incoming_dept = department_for_path(folder_path) if folder_path else None

    job = None
    for lt, lv in strong:
        if lv:
            job = find_job_by_link(lt, lv)
            if job:
                break
    if job is not None and strict_department and _department_conflict(
            job, incoming_dept):
        raise DepartmentConflict(
            f"folder {folder_path!r} is under the {incoming_dept} root but "
            f"is already linked to {job['canon_key']!r}, owned by "
            f"{job.get('department')}")
    if job is None and name:
        job = find_job_by_name(name)
        if job is not None and strict_department and _department_conflict(
                job, incoming_dept):
            job = None
    if job is None:
        if not create:
            return None
        dn = (display_name or name).strip()
        if not dn:
            return None
        clash = get_job(canon_key(dn))
        if strict_department and _department_conflict(clash, incoming_dept):
            raise DepartmentConflict(
                f"{dn!r} already exists as a {clash.get('department')} job; "
                f"the incoming folder is {incoming_dept}. Rename one of them "
                f"so the two franchises' jobs stay distinct.")
        key = upsert_job(display_name=dn, department=incoming_dept or "")
        job = get_job(key)
        if job is None:
            return None

    key = job["canon_key"]
    if name:
        nk = canon_key(name)
        if nk and nk != key and not _is_primary_job_key(nk):
            add_alias(key, name, source=source)
    for lt, lv in strong:
        if lv:
            set_link(key, lt, lv, added_by=source)
    return get_job(key)


def job_identity(name: str):
    job = find_job_by_name(name)
    if not job:
        return None
    key = job["canon_key"]
    return {"job": job, "aliases": get_aliases(key),
            "links": get_links(key)}


# ── the batched audit lookup ────────────────────────────────────────────

def card_display_names_for(names) -> dict:
    """{input_name: display_name} for names whose job has a Trello card.

    Three requests total regardless of row count. The per-row form cost two
    round trips PER ROW — invisible against local SQLite, ~36s against a
    hosted database on a 300-row audit.
    """
    wanted = {}
    for n in names or ():
        k = canon_key(n or "")
        if k:
            wanted.setdefault(k, []).append(n)
    if not wanted:
        return {}
    keys = list(wanted)
    out = {}

    jobs = _rows("jobs", canon_key=_in(keys),
                 select="canon_key,display_name")
    direct = {j["canon_key"] for j in jobs}
    carded = {l["canon_key"] for l in
              _rows("job_links", canon_key=_in(keys),
                    link_type=f"eq.{LINK_TRELLO}", select="canon_key")}
    for j in jobs:
        if j["canon_key"] in carded and (j.get("display_name") or ""):
            for orig in wanted.get(j["canon_key"], ()):
                out[orig] = j["display_name"]

    # Alias pass — ONLY for names with no direct jobs row. A name that is
    # its own (uncarded) job must not fall through to someone else's alias;
    # live data has 'Gabriel Ramirez' as both.
    left = [k for k in keys if k not in direct]
    if left:
        al = _rows("job_aliases", alias_canon=_in(left),
                   select="alias_canon,canon_key")
        if al:
            akeys = list({a["canon_key"] for a in al})
            ajobs = {j["canon_key"]: j for j in
                     _rows("jobs", canon_key=_in(akeys),
                           select="canon_key,display_name")}
            acards = {l["canon_key"] for l in
                      _rows("job_links", canon_key=_in(akeys),
                            link_type=f"eq.{LINK_TRELLO}",
                            select="canon_key")}
            for a in al:
                j = ajobs.get(a["canon_key"])
                if j and a["canon_key"] in acards and (j.get("display_name")):
                    for orig in wanted.get(a["alias_canon"], ()):
                        out.setdefault(orig, j["display_name"])
    return out


def carriers_for(names) -> dict:
    """{input_name: carrier} for names resolving to a job with one.

    Batched for the same reason as `card_display_names_for` — the audit
    shapes hundreds of rows at once, and a per-row request would be tens
    of seconds against a hosted database.

    No card requirement here: the carrier is a fact about the job, known
    long before anyone pins a card.
    """
    wanted = {}
    for n in names or ():
        k = canon_key(n or "")
        if k:
            wanted.setdefault(k, []).append(n)
    if not wanted:
        return {}
    keys = list(wanted)
    out = {}

    jobs = _rows("jobs", canon_key=_in(keys), select="canon_key,carrier")
    direct = {j["canon_key"] for j in jobs}
    for j in jobs:
        val = (j.get("carrier") or "").strip()
        if val:
            for orig in wanted.get(j["canon_key"], ()):
                out[orig] = val

    # Alias pass for names with no direct row — same trap as above.
    left = [k for k in keys if k not in direct]
    if left:
        al = _rows("job_aliases", alias_canon=_in(left),
                   select="alias_canon,canon_key")
        if al:
            akeys = list({a["canon_key"] for a in al})
            ajobs = {j["canon_key"]: j for j in
                     _rows("jobs", canon_key=_in(akeys),
                           select="canon_key,carrier")}
            for a in al:
                j = ajobs.get(a["canon_key"])
                val = ((j or {}).get("carrier") or "").strip()
                if val:
                    for orig in wanted.get(a["alias_canon"], ()):
                        out.setdefault(orig, val)
    return out


# ── departments ─────────────────────────────────────────────────────────

def department_of_job(canon_key_value: str):
    return (get_job(canon_key_value) or {}).get("department") or None


def set_department(canon_key_value: str, department: str, *,
                   overwrite: bool = False) -> bool:
    dept = (department or "").strip()
    if not (canon_key_value and dept):
        return False
    p = {"canon_key": f"eq.{canon_key_value}"}
    if not overwrite:
        p["department"] = "is.null"
    res = _sb.rest("PATCH", "jobs", params=p, body={"department": dept},
                   prefer="return=representation")
    return bool(res)


def count_by_department() -> dict:
    out = {}
    for j in _rows("jobs", select="department"):
        k = (j.get("department") or "").strip() or "unknown"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def find_dead_folder_links() -> list:
    """Folder links whose path no longer exists on disk.

    Disk-local even on the shared backend: the paths are per-machine, so
    "does this folder exist?" can only be answered here. On a machine that
    doesn't mount the share, everything looks dead — which is exactly why
    `prune_dead_folder_links` must never run unattended.
    """
    import os
    out = []
    for job in iter_jobs():
        for l in get_links(job["canon_key"], LINK_FOLDER):
            p = l["link_value"]
            if p and not os.path.isdir(p):
                out.append({"canon_key": job["canon_key"],
                            "display_name": job.get("display_name") or "",
                            "path": p})
    return out


def prune_dead_folder_links() -> dict:
    """Drop every folder link whose path is gone. Only with the share
    REACHABLE — otherwise every path looks dead and the lot is wiped."""
    dead = find_dead_folder_links()
    for d in dead:
        remove_link(d["canon_key"], LINK_FOLDER, d["path"])
    return {"removed": len(dead), "links": dead}


def find_department_conflicts() -> list:
    out = []
    jobs = {j["canon_key"]: j for j in
            _rows("jobs", select="canon_key,display_name,department")}
    links = _rows("job_links", link_type=f"eq.{LINK_FOLDER}",
                  select="canon_key,link_value")
    by_job = {}
    for l in links:
        by_job.setdefault(l["canon_key"], []).append(l["link_value"])
    for key, paths in by_job.items():
        depts = {d for d in (department_for_path(p) for p in paths) if d}
        if not depts:
            continue
        stored = (jobs.get(key, {}).get("department") or "").strip()
        if len(depts) > 1 or (stored and stored not in depts):
            out.append({"canon_key": key,
                        "display_name": jobs.get(key, {}).get("display_name"),
                        "stored": stored or None,
                        "folder_departments": sorted(depts),
                        "folders": paths})
    return out


# ── children ────────────────────────────────────────────────────────────

def set_child(parent_canon: str, name: str, *, kind: str = "",
              ordinal=None, folder_path: str = "", trello_card: str = "",
              companycam: str = "", department: str = "",
              property: str = "", unit: str = "", claim_date: str = "",
              metadata: dict | None = None) -> dict:
    """See the SQLite twin. `property` / `unit` / `claim_date` are the v8
    levels between a client and a claim (007_child_levels.sql)."""
    parent_canon = (parent_canon or "").strip()
    name = (name or "").strip()
    if not (parent_canon and name):
        return {}
    if not kind:
        kind, ordinal = classify_child(name)
    fp = _norm_link(LINK_FOLDER, folder_path) if folder_path else ""
    card = _norm_link(LINK_TRELLO, trello_card) if trello_card else ""
    now = _now_iso()
    # None means "leave alone" — {} would blank a child's settings on any
    # unrelated set_child call, and backfill_children calls it per folder.
    md = json.dumps(metadata) if isinstance(metadata, dict) else None
    cur = _one("job_children", parent_canon=f"eq.{parent_canon}",
               name=f"eq.{name}", select="*")
    if cur is None:
        _sb.rest("POST", "job_children", body={
            "parent_canon": parent_canon, "name": name, "kind": kind,
            "ordinal": ordinal, "folder_path": fp or None,
            "trello_card": card or None, "companycam": companycam or None,
            "department": department or None,
            "created_at": now, "updated_at": now,
            "property": property or None, "unit": unit or None,
            "claim_date": claim_date or None,
            # Only sent when there is something to store. Sending it
            # unconditionally makes every set_child fail with PGRST204 on a
            # project where 004_job_settings.sql hasn't run yet — which
            # would take backfill_children down with it, over a column that
            # call never uses.
            **({"metadata_json": md} if md is not None else {}),
        }, prefer="resolution=merge-duplicates")
    else:
        _sb.rest("PATCH", "job_children",
                 params={"parent_canon": f"eq.{parent_canon}",
                         "name": f"eq.{name}"},
                 body={
                     "kind": kind or cur.get("kind"),
                     "ordinal": ordinal if ordinal is not None
                                else cur.get("ordinal"),
                     "folder_path": fp or cur.get("folder_path"),
                     "trello_card": card or cur.get("trello_card"),
                     "companycam": companycam or cur.get("companycam"),
                     "department": department or cur.get("department"),
                     "updated_at": now,
                     # Blank never overwrites — a caller setting only the
                     # card must not wipe a unit recorded earlier.
                     "property": property or cur.get("property"),
                     "unit": unit or cur.get("unit"),
                     "claim_date": claim_date or cur.get("claim_date"),
                     **({"metadata_json": md} if md is not None else {}),
                 })
    return _one("job_children", parent_canon=f"eq.{parent_canon}",
                name=f"eq.{name}", select="*") or {}


def all_children() -> list:
    """Every child row in ONE request — see the SQLite twin. `_rows` pages,
    so this stays complete past the 1000-row cap."""
    return _rows("job_children", select="*",
                 order="parent_canon.asc,ordinal.asc.nullslast,name.asc")


def children_of(parent_canon: str, *, kind: str = "") -> list:
    parent_canon = (parent_canon or "").strip()
    if not parent_canon:
        return []
    p = {"parent_canon": f"eq.{parent_canon}", "select": "*",
         "order": "ordinal.asc.nullslast,name.asc"}
    if kind:
        p["kind"] = f"eq.{kind}"
    return _rows("job_children", **p)


def find_child_by_folder(folder_path: str):
    fp = _norm_link(LINK_FOLDER, folder_path)
    if not fp:
        return None
    return _one("job_children", folder_path=f"eq.{fp}", select="*")


def find_child_by_card(trello_card: str):
    card = _norm_link(LINK_TRELLO, trello_card)
    if not card:
        return None
    return _one("job_children", trello_card=f"eq.{card}", select="*")


def remove_child(parent_canon: str, name: str) -> bool:
    res = _sb.rest("DELETE", "job_children",
                   params={"parent_canon": f"eq.{(parent_canon or '').strip()}",
                           "name": f"eq.{(name or '').strip()}"},
                   prefer="return=representation")
    return bool(res)


def find_units_of(parent_canon: str) -> list:
    return children_of(parent_canon)


def find_property_of(canon_key_value: str):
    """The client a job is a child of, via its folder — the same rule as
    SQLite, derived from the folder tree rather than a name."""
    if not canon_key_value:
        return None
    paths = [l["link_value"] for l in
             get_links(canon_key_value, LINK_FOLDER)]
    for p in paths:
        ch = find_child_by_folder(p)
        if ch and ch.get("parent_canon"):
            return get_job(ch["parent_canon"])
    return None


def group_by_property(canon_keys) -> dict:
    keys = [k for k in canon_keys if k]
    if not keys:
        return {}
    links = _rows("job_links", canon_key=_in(keys),
                  link_type=f"eq.{LINK_FOLDER}",
                  select="canon_key,link_value")
    paths = [l["link_value"] for l in links]
    parent_by_path = {}
    if paths:
        for ch in _rows("job_children", folder_path=_in(paths),
                        select="folder_path,parent_canon"):
            parent_by_path[ch["folder_path"]] = ch["parent_canon"]
    parent_map = {}
    for l in links:
        p = parent_by_path.get(l["link_value"])
        if p:
            parent_map.setdefault(l["canon_key"], p)
    out = {}
    for k in keys:
        out.setdefault(parent_map.get(k) or k, []).append(k)
    return out


# ── events ──────────────────────────────────────────────────────────────

def log_event(canon_key_value: str, event_type: str, *,
              payload: dict | None = None) -> None:
    if not (canon_key_value and event_type):
        return
    body = {"canon_key": canon_key_value, "event_type": event_type,
            "event_at": _now_iso(),
            "payload_json": json.dumps(payload) if payload else None}
    try:
        user = _sb.current_user() or {}
        actor = user.get("display_name") or user.get("email")
        if actor:
            body["actor"] = actor
    except Exception:
        pass
    _sb.rest("POST", "job_events", body=body)


def list_events(canon_key_value: str, event_type: str = "",
                limit: int = 100) -> list[dict]:
    """Newest-first structured events for one job."""
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    params = {"canon_key": f"eq.{canon_key_value}",
              "select": "id,canon_key,event_type,event_at,payload_json,actor",
              "order": "id.desc", "limit": str(limit)}
    if event_type:
        params["event_type"] = f"eq.{event_type}"
    out = []
    for row in _rows("job_events", **params):
        item = dict(row)
        raw = item.pop("payload_json", None)
        try:
            item["payload"] = json.loads(raw or "{}")
        except (TypeError, ValueError):
            item["payload"] = {}
        out.append(item)
    return out


# ── merge ───────────────────────────────────────────────────────────────

def _reparent_children(from_key: str, into_key: str) -> int:
    """Move a merged-away job's children onto the survivor.

    MUST run before the `jobs` row is deleted. `job_children.parent_canon`
    is declared `references jobs (canon_key) on delete cascade`
    (003_job_children.sql:20), so deleting the loser takes every one of
    its units and claims with it — silently, and with no orphan left
    behind to notice afterwards, because the foreign key makes orphans
    impossible by construction.

    That was live: merging `avana springs greystar` would have destroyed
    all seven of its unit rows, each carrying its own folder, Trello card
    and CompanyCam project.

    (The SQLite twin has no foreign key at all, so there the same merge
    ORPHANED the children instead. Same function, opposite outcome — the
    reason this now lives in both backends.)
    """
    kids = _rows("job_children", parent_canon=f"eq.{from_key}", select="*")
    if not kids:
        return 0
    taken = [k.get("name") for k in
             _rows("job_children", parent_canon=f"eq.{into_key}", select="name")]
    moved = 0
    for kid in kids:
        name = dedupe_child_name(kid.get("name"), taken)
        try:
            _sb.rest("PATCH", "job_children",
                     params={"id": f"eq.{kid['id']}"},
                     body={"parent_canon": into_key, "name": name,
                           "updated_at": _now_iso()})
        except Exception:
            # One stubborn row must not abort the merge mid-way and leave
            # the job half-folded; the rest still move.
            continue
        taken.append(name)
        moved += 1
    return moved


def merge_jobs(into_key: str, from_keys) -> dict:
    """Fold jobs together. Refuses across franchises, like SQLite."""
    into_key = (into_key or "").strip()
    if not into_key:
        return {"merged": 0}
    into = get_job(into_key)
    into_dept = (into or {}).get("department")
    merged, skipped, moved_kids = 0, [], 0
    for fk in from_keys or ():
        fk = (fk or "").strip()
        if not fk or fk == into_key:
            continue
        row = get_job(fk)
        if row is None:
            continue
        if into_dept and row.get("department") and \
                row["department"] != into_dept:
            skipped.append(fk)
            continue
        for a in _rows("job_aliases", canon_key=f"eq.{fk}", select="*"):
            # force: the loser's rows are still here (deleted next line),
            # so the ambiguity guard would refuse every one of them.
            add_alias(into_key, a["alias"], source=a.get("source") or "merge",
                      force=True)
        _sb.rest("DELETE", "job_aliases", params={"canon_key": f"eq.{fk}"})
        for l in _rows("job_links", canon_key=f"eq.{fk}", select="*"):
            set_link(into_key, l["link_type"], l["link_value"],
                     added_by=l.get("added_by") or "merge")
        _sb.rest("DELETE", "job_links", params={"canon_key": f"eq.{fk}"})
        if row.get("display_name"):
            add_alias(into_key, row["display_name"], source="merge", force=True)
        # Carry the loser's history over rather than strand it under a
        # canon_key that no longer names a job — see the SQLite twin.
        _sb.rest("PATCH", "job_events", params={"canon_key": f"eq.{fk}"},
                 body={"canon_key": into_key})
        moved_kids += _reparent_children(fk, into_key)
        _sb.rest("DELETE", "jobs", params={"canon_key": f"eq.{fk}"})
        # The fold IS the rename when the two names really differ.
        if is_material_rename(row.get("display_name"),
                              (into or {}).get("display_name")):
            try:
                log_event(into_key, EVENT_RENAMED,
                          payload={"from": row.get("display_name"),
                                   "to": (into or {}).get("display_name"),
                                   "via": "merge"})
            except Exception:
                pass
        merged += 1
    out = {"merged": merged}
    if moved_kids:
        out["children_moved"] = moved_kids
    if skipped:
        out["skipped_department_conflict"] = skipped
    return out


def delete_job(canon_key_value: str) -> dict:
    """Delete one shared job graph row; external folders/cards stay put."""
    key = (canon_key_value or "").strip()
    if not key:
        return {"deleted": 0}
    row = get_job(key)
    if row is None:
        return {"deleted": 0}
    kids = _rows("job_children", parent_canon=f"eq.{key}", select="id")
    # Explicit for parity with SQLite and to make the returned count honest;
    # the database FK would cascade these rows as well.
    if kids:
        _sb.rest("DELETE", "job_children",
                 params={"parent_canon": f"eq.{key}"})
    _sb.rest("DELETE", "jobs", params={"canon_key": f"eq.{key}"})
    return {"deleted": 1, "display_name": row.get("display_name") or key,
            "children_deleted": len(kids)}


# ── bulk / maintenance: SQLite-side only ────────────────────────────────

def backfill_departments(*a, **k):    _unsupported("backfill_departments")
def export_db(*a, **k):               _unsupported("export_db")
def import_db(*a, **k):               _unsupported("import_db")
def reset_db_path(*a, **k):           _unsupported("reset_db_path")


# ── backup snapshot ─────────────────────────────────────────────────────

# Every table the cloud owns.
#
# Deliberately NOT export_db's list. export_db is a SHARING format: it
# filters links down to Trello + folders and drops job_events outright,
# because a machine-specific SharePoint cache means nothing on another
# franchise's PC. A backup wants the opposite — it has to restore what
# was actually there, so it takes everything verbatim, including the
# tables that ARE a job's identity: job_children (the whole unit/claim
# hierarchy), job_events (name history), and the companycam / workcenter
# links export_db throws away.
#
# Reusing export_db here would have produced a backup that looked fine
# and silently lacked every child row.
_SNAPSHOT_TABLES = (
    "jobs", "job_aliases", "job_links", "job_children", "job_events",
    "job_lifecycle", "job_stage_transitions", "meta",
    "app_user_departments",
)


def snapshot(path: str = "") -> dict:
    """Dump every cloud table to JSON for disaster recovery.

    Returns {ok, counts:{table: n}, errors:{table: str}, path}. Writing
    is skipped when `path` is empty — the caller gets the payload back
    under "data" instead, which is what the tests use.

    A partial snapshot is NOT written. `ok` goes False, the errors come
    back, and no file appears — so a file at this path is always a
    complete one. Discovering a missing table at restore time is the one
    moment it can't be fixed, and a short file that looks fine is worse
    than an obvious absence.
    """
    import os

    payload = {
        "schema_version": SCHEMA_VERSION,
        "taken_at": _now_iso(),
        "taken_by": os.environ.get("USERNAME", ""),
        "tables": {},
    }
    counts, errors = {}, {}
    for table in _SNAPSHOT_TABLES:
        try:
            rows = _rows(table)
        except Exception as ex:
            # Keep going. Losing app_user_departments to a permission
            # rule should not cost us the jobs table too.
            errors[table] = f"{type(ex).__name__}: {ex}"
            continue
        payload["tables"][table] = rows
        counts[table] = len(rows)

    out = {"ok": not errors, "counts": counts, "errors": errors, "path": path}
    if not path:
        out["data"] = payload
        return out
    if errors:
        return out          # incomplete — leave no file behind at all

    # Write to .part then rename, matching data_backup: a snapshot half
    # written when the machine drops must not look like a usable one.
    tmp = path + ".part"
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as ex:
        try:
            os.remove(tmp)
        except OSError:
            pass
        out["ok"] = False
        out["errors"]["_write"] = f"{type(ex).__name__}: {ex}"
    return out


# How many rows go in one PostgREST request. Big enough that a full
# workspace is a handful of calls, small enough that one failure doesn't
# cost the whole sync.
_SYNC_CHUNK = 200


def _chunks(seq, n=_SYNC_CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def sync_from_trello(*, exclude_quality: bool = True,
                     exclude_logs: bool = True,
                     lane_filter=None, progress_cb=None) -> dict:
    """Refresh the index from Trello, in bulk.

    This was unsupported for a real reason: the SQLite version writes per
    card — upsert_job + add_alias + set_link — which against a hosted
    database is three round trips times every open card, so a workspace
    sync was thousands of requests. Nobody was going to wait, so the
    shared index simply stopped learning anything from Trello after the
    cutover: no carriers, no claim numbers, no new jobs.

    Same work, batched: read the existing rows for every key at once,
    merge in Python, then upsert in chunks. A full workspace is a handful
    of requests.

    The SQLite semantics are preserved deliberately, because conformance
    compares the two:
      * a blank from Trello never overwrites a stored value,
      * first_seen_at survives, last_seen_at moves,
      * a material rename still records a rename event and keeps the old
        name as an alias.
    """
    # Local import, matching upsert_job: the column list is owned by the
    # SQLite module so the two backends can't drift on which fields exist.
    from ems_db_sqlite import _TEXT_COLUMNS
    import trello_job_sync as _walk
    found = _walk.collect(exclude_quality=exclude_quality,
                          exclude_logs=exclude_logs,
                          lane_filter=lane_filter,
                          progress_cb=progress_cb)
    records = found["records"]
    out = {"boards": found["boards"], "cards": len(records),
           "jobs_upserted": 0, "links_added": 0}
    if not records:
        return out

    # Before anything is keyed: point each card at the job it already
    # belongs to when the index holds the other spelling. Both the card's
    # key and its swapped form are looked up in ONE read, so this costs a
    # request, not a request per card.
    from job_name_issues import swapped_name as _swap
    probe = set()
    for rec in records:
        k = rec.get("canon_key") or ""
        if k:
            probe.add(k)
        sw = _swap(rec.get("display_name") or "")
        if sw:
            sk = canon_key(sw)
            if sk:
                probe.add(sk)
    known = set()
    for part in _chunks(sorted(probe)):
        for row in _rows("jobs", canon_key=_in(part), select="canon_key"):
            known.add(row["canon_key"])
    _walk.resolve_against_existing(records, lambda k: k in known)

    # One card per key wins the job fields — a client with several cards
    # would otherwise fight itself. Every card still gets its own link,
    # which is how multi-card clients stay reachable.
    by_key: dict = {}
    for rec in records:
        by_key[rec["canon_key"]] = rec
    keys = list(by_key)

    existing: dict = {}
    for part in _chunks(keys):
        for row in _rows("jobs", canon_key=_in(part), select="*"):
            existing[row["canon_key"]] = row

    now = _now_iso()
    job_rows, alias_rows, rename_events = [], [], []
    for key, rec in by_key.items():
        prior = existing.get(key)
        name = rec["display_name"]
        # Every column the card stated, not just claim + carrier. The
        # collector already dropped blanks, and the partial-update rule
        # below means a card that omits a field never clears one.
        supplied = dict(rec.get("columns") or {})
        supplied.update({"claim_number": rec["claim_number"],
                         "carrier": rec["carrier"],
                         "status": rec["status"]})
        md_json = json.dumps({"board": rec["board"], "lane": rec["lane"]})
        row = {"canon_key": key, "display_name": name,
               "last_seen_at": now, "metadata_json": md_json}
        if prior is None:
            row["first_seen_at"] = now
            row["department"] = None
            for col in _TEXT_COLUMNS:
                row[col] = supplied.get(col) or None
        else:
            row["first_seen_at"] = prior.get("first_seen_at") or now
            row["department"] = prior.get("department")
            for col in _TEXT_COLUMNS:
                # Blank in never clears what's stored — the same
                # partial-update rule upsert_job applies one row at a
                # time. Without it a card missing its carrier would
                # ERASE a carrier somebody typed in.
                row[col] = supplied.get(col) or prior.get(col)
            was = prior.get("display_name") or ""
            if is_material_rename(was, name):
                rename_events.append((key, was, name))
                alias_rows.append({"canon_key": key, "alias": was,
                                   "alias_canon": canon_key(was),
                                   "source": "rename"})
        job_rows.append(row)
        alias_rows.append({"canon_key": key, "alias": name,
                           "alias_canon": canon_key(name),
                           "source": "trello"})
        # The card's own spelling when it was redirected to an existing
        # job — so a search for the card title still finds it.
        for extra in (rec.get("aliases") or ()):
            if extra:
                alias_rows.append({"canon_key": key, "alias": extra,
                                   "alias_canon": canon_key(extra),
                                   "source": "trello"})

    for part in _chunks(job_rows):
        _sb.rest("POST", "jobs", body=part,
                 prefer="resolution=merge-duplicates")
        out["jobs_upserted"] += len(part)

    # Aliases are keyed on (canon_key, alias_canon); re-syncing the same
    # board must not pile up duplicates.
    seen_alias = set()
    deduped = []
    for a in alias_rows:
        sig = (a["canon_key"], a["alias_canon"])
        if a["alias_canon"] and sig not in seen_alias:
            seen_alias.add(sig)
            deduped.append(a)
    for part in _chunks(deduped):
        try:
            _sb.rest("POST", "job_aliases", body=part,
                     prefer="resolution=merge-duplicates")
        except Exception:
            pass          # an alias clash must not fail the whole sync

    # The column is link_value, and trello_card is a STRONG link type, so
    # it goes through _norm_link exactly as set_link does — a pin stored
    # un-canonicalised is a pin nothing else can match.
    link_rows = [{
        "canon_key": rec["canon_key"], "link_type": LINK_TRELLO,
        "link_value": _norm_link(LINK_TRELLO, rec["card_id"]),
        "added_by": "sync_from_trello", "added_at": now,
        "metadata_json": json.dumps({"board": rec["board"],
                                     "lane": rec["lane"]}),
    } for rec in records if rec.get("card_id")]
    link_rows = [r for r in link_rows if r["link_value"]]
    for part in _chunks(link_rows):
        _sb.rest("POST", "job_links", body=part,
                 prefer="resolution=merge-duplicates")
        out["links_added"] += len(part)

    for key, was, now_name in rename_events:
        try:
            log_event(key, EVENT_RENAMED, payload={"from": was,
                                                   "to": now_name})
        except Exception:
            pass          # history is worth having, not worth failing for
    return out


def _lifecycle_iso(value):
    try:
        return datetime.fromisoformat(str(value).split("+")[0].rstrip("Z"))
    except (TypeError, ValueError):
        return None


def _utc_now_naive():
    """Current UTC time in the naive format used by existing lifecycle rows."""
    return datetime.now(UTC).replace(tzinfo=None)


def lifecycle_upsert(entry):
    """Shared equivalent of SQLite's transition-aware card upsert."""
    card_id = (entry or {}).get("card_id")
    if not card_id:
        return None
    prior = _one("job_lifecycle", card_id=f"eq.{card_id}", select="*")
    now = _now_iso()
    new_stage = entry.get("current_stage") or ""
    transition = None
    if prior:
        old_stage = prior.get("current_stage") or ""
        changed = bool(new_stage and new_stage != old_stage)
        entered = now if changed else (prior.get("stage_entered_at") or now)
        billed = prior.get("billed_at") or (now if new_stage == "ar" else None)
        paid = prior.get("paid_at") or (now if new_stage == "paid" else None)
        if changed and old_stage:
            old_dt = _lifecycle_iso(prior.get("stage_entered_at"))
            days = max(0, (_utc_now_naive() - old_dt).days) if old_dt else 0
            transition = {
                "card_id": card_id,
                "client_canon": entry.get("client_canon") or "",
                "from_stage": old_stage, "to_stage": new_stage,
                "transitioned_at": now, "days_in_from_stage": days,
            }
    else:
        entered = now
        last_dt = _lifecycle_iso(entry.get("last_activity_at"))
        if last_dt and last_dt < _utc_now_naive():
            entered = last_dt.replace(microsecond=0).isoformat()
        billed = now if new_stage == "ar" else None
        paid = now if new_stage == "paid" else None
    body = {
        "card_id": card_id,
        "client_canon": entry.get("client_canon") or "",
        "client_display": entry.get("client_display") or "",
        "board_id": entry.get("board_id") or "",
        "board_name": entry.get("board_name") or "",
        "list_id": entry.get("list_id") or "",
        "list_name": entry.get("list_name") or "",
        "current_stage": new_stage, "stage_entered_at": entered,
        "created_at": ((prior or {}).get("created_at") or
                       entry.get("created_at")),
        "last_activity_at": entry.get("last_activity_at"),
        "billed_at": billed, "paid_at": paid,
        "card_url": entry.get("card_url") or "",
        "owner": entry.get("owner") or "", "updated_at": now,
        "actions_synced_at": (None if transition else
                              (prior or {}).get("actions_synced_at")),
    }
    rows = _sb.rest("POST", "job_lifecycle", body=body,
                    prefer="resolution=merge-duplicates,return=representation")
    if transition:
        _sb.rest("POST", "job_stage_transitions", body=transition,
                 prefer="return=minimal")
    return (rows or [body])[0]


def lifecycle_delete(card_id):
    if not card_id:
        return None
    _sb.rest("DELETE", "job_stage_transitions",
             params={"card_id": f"eq.{card_id}"})
    _sb.rest("DELETE", "job_lifecycle", params={"card_id": f"eq.{card_id}"})
    return True


def lifecycle_purge_where(predicate) -> int:
    rows = _rows("job_lifecycle",
                 select="card_id,client_display,board_name,list_name")
    ids = [row.get("card_id") for row in rows if predicate(dict(row))]
    for card_id in ids:
        lifecycle_delete(card_id)
    return len(ids)


def lifecycle_needs_action_enrichment(*, limit=None):
    rows = _rows("job_lifecycle",
                 select="card_id,list_id,stage_entered_at,current_stage,actions_synced_at")
    rows = [row for row in rows if not row.get("actions_synced_at")]
    rows.sort(key=lambda row: row.get("stage_entered_at") or "")
    return rows[:int(limit)] if limit else rows


def lifecycle_set_stage_entered(card_id, *, stage_entered_at,
                                 mark_actions_synced=True):
    if not card_id or not stage_entered_at:
        return None
    body = {"stage_entered_at": stage_entered_at}
    if mark_actions_synced:
        body["actions_synced_at"] = _now_iso()
    _sb.rest("PATCH", "job_lifecycle",
             params={"card_id": f"eq.{card_id}"}, body=body,
             prefer="return=minimal")
    return True


def lifecycle_mark_actions_synced(card_id):
    if not card_id:
        return None
    _sb.rest("PATCH", "job_lifecycle",
             params={"card_id": f"eq.{card_id}"},
             body={"actions_synced_at": _now_iso()},
             prefer="return=minimal")
    return True


def backfill_stage_entered_dates() -> int:
    rows = _rows("job_lifecycle",
                 select="card_id,stage_entered_at,last_activity_at")
    changed = 0
    for row in rows:
        entered = _lifecycle_iso(row.get("stage_entered_at"))
        activity = _lifecycle_iso(row.get("last_activity_at"))
        if entered and activity and activity < entered:
            lifecycle_set_stage_entered(
                row.get("card_id"), stage_entered_at=row["last_activity_at"],
                mark_actions_synced=False)
            changed += 1
    return changed


def list_transitions(*, since_iso=None, from_stage=None, card_id=None,
                     limit=None, order="DESC"):
    params = {"select": "*", "order":
              "transitioned_at.asc" if str(order).upper() == "ASC"
              else "transitioned_at.desc"}
    if since_iso:
        params["transitioned_at"] = f"gte.{since_iso}"
    if from_stage:
        params["from_stage"] = f"eq.{from_stage}"
    if card_id:
        params["card_id"] = f"eq.{card_id}"
    if limit:
        params["limit"] = str(int(limit))
    return _rows("job_stage_transitions", **params)


def lifecycle_list(paid_window_days=30):
    rows = _rows("job_lifecycle", select="*")
    if paid_window_days is not None:
        cutoff = _utc_now_naive() - timedelta(days=paid_window_days)
        rows = [row for row in rows
                if row.get("current_stage") != "paid"
                or not row.get("paid_at")
                or ((_lifecycle_iso(row.get("paid_at")) or datetime.min) >= cutoff)]
    return sorted(rows, key=lambda row: row.get("stage_entered_at") or "")


def lifecycle_get(card_id):
    if not card_id:
        return None
    return _one("job_lifecycle", card_id=f"eq.{card_id}", select="*")


def lifecycle_counts_by_stage(paid_window_days=30):
    counts = {}
    for row in lifecycle_list(paid_window_days=paid_window_days):
        stage = row.get("current_stage") or ""
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def __getattr__(name):
    if name in ("export_db", "import_db"):
        def _stub(*a, **k):
            _unsupported(name)
        return _stub
    raise AttributeError(name)
