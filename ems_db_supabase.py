"""Job index — shared Postgres backend over Supabase's PostgREST API.

Same public surface as `ems_db_sqlite`; `ems_db` picks between them. All
identity logic (canon_key, link normalization, the department→root map,
the child classifier) comes from `ems_db_common`, so the two backends
cannot disagree about what a job IS.

Transport is `supabase_client`: plain HTTPS via urllib, authenticated as
the signed-in user so Row-Level Security applies. There is no database
password anywhere — the publishable key identifies the project and grants
nothing on its own.

What is NOT implemented here
----------------------------
`sync_from_trello`, `export_db`, `import_db` and the `lifecycle_*` family
stay SQLite-side. They are bulk/maintenance operations over the local
cache, not part of the job graph the app reads on every render, and doing
them over REST would mean thousands of round trips. They raise a clear
error rather than silently doing half the work.

Round-trip discipline
---------------------
Every call here is network latency, so anything the UI does per row must
be batched — `card_display_names_for` is the reason the audit render was
rewritten from ~600 queries to one. When adding a function, assume 60ms
per request and design accordingly.
"""
from __future__ import annotations

import json

import supabase_client as _sb
from ems_db_common import (            # noqa: F401 — re-exported as API
    _UNIT_DETECT_PATTERNS, detect_property_and_unit, canon_key,
    LINK_FOLDER, LINK_TRELLO, LINK_COMPANYCAM, _STRONG_LINK_TYPES,
    _norm_link, invalidate_department_cache, department_for_path,
    split_department_path, rebase_department_path,
    CHILD_CLAIM, CHILD_UNIT, CHILD_SUBJOB, classify_child, _now_iso,
    EVENT_RENAMED, is_material_rename,
)

SCHEMA_VERSION = 5


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
    if link_type in _STRONG_LINK_TYPES:
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
        dept = department_for_path(link_value)
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
    return r["link_value"] if r else None


def get_links(canon_key_value: str, link_type: str = "") -> list:
    if not canon_key_value:
        return []
    p = {"canon_key": f"eq.{canon_key_value}", "select": "*",
         "order": "added_at.asc"}
    if link_type:
        p["link_type"] = f"eq.{link_type}"
    return _rows("job_links", **p)


def remove_link(canon_key_value: str, link_type: str,
                link_value: str = "") -> None:
    if not (canon_key_value and link_type):
        return
    p = {"canon_key": f"eq.{canon_key_value}", "link_type": f"eq.{link_type}"}
    if link_value:
        # Normalized on the way in by set_link — must match here or the
        # delete silently removes nothing.
        p["link_value"] = f"eq.{_norm_link(link_type, link_value)}"
    _sb.rest("DELETE", "job_links", params=p)


def find_job_by_link(link_type: str, link_value: str):
    nv = _norm_link(link_type, link_value)
    if not (link_type and nv):
        return None
    l = _one("job_links", link_type=f"eq.{link_type}", link_value=f"eq.{nv}",
             select="canon_key", order="added_at.asc")
    return get_job(l["canon_key"]) if l else None


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
              metadata: dict | None = None) -> dict:
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
        if user.get("email"):
            body["actor"] = user["email"]
    except Exception:
        pass
    _sb.rest("POST", "job_events", body=body)


# ── merge ───────────────────────────────────────────────────────────────

def merge_jobs(into_key: str, from_keys) -> dict:
    """Fold jobs together. Refuses across franchises, like SQLite."""
    into_key = (into_key or "").strip()
    if not into_key:
        return {"merged": 0}
    into = get_job(into_key)
    into_dept = (into or {}).get("department")
    merged, skipped = 0, []
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
    if skipped:
        out["skipped_department_conflict"] = skipped
    return out


# ── bulk / maintenance: SQLite-side only ────────────────────────────────

def backfill_departments(*a, **k):    _unsupported("backfill_departments")
def export_db(*a, **k):               _unsupported("export_db")
def import_db(*a, **k):               _unsupported("import_db")
def sync_from_trello(*a, **k):        _unsupported("sync_from_trello")
def reset_db_path(*a, **k):           _unsupported("reset_db_path")


def __getattr__(name):
    """lifecycle_* (the Pipeline panel) stays on the local index — it is a
    projection of Trello that would cost thousands of round trips here."""
    if name.startswith("lifecycle_") or name in (
            "backfill_stage_entered_dates", "list_transitions"):
        def _stub(*a, **k):
            _unsupported(name)
        return _stub
    raise AttributeError(name)
