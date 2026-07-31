"""Shared local job index — `ems_jobs.db`.

A SQLite cache that every tool reads from and writes to. Trello is the
source of truth; this DB is just an indexed projection of Trello +
folder pins + run-doc-derived state, so every tool sees one consistent
view of every job regardless of which surface first discovered it.

Schema (auto-created on first use):

    jobs          — one row per real-world job, keyed by canonicalized
                    name (`canon_key`). Stores claim, carrier, status,
                    received date.
    job_aliases   — name variants (comma-swap, suffix, date suffix) so
                    `find_job_by_name` resolves the same job from any
                    surface's spelling.
    job_links     — references into external systems: trello_card,
                    folder_path, companycam_project, sp_folder, wc_folder,
                    sheet_row, xa_link. Multiple links per (job, type)
                    supported. ("od_folder" was this module's original name
                    for the job folder; the live constant is LINK_FOLDER =
                    "folder_path". Both are read where it matters — see
                    export_db — so pre-rename databases still export.)
    job_events    — append-only audit trail (per-machine, not exported).
    meta          — schema version + arbitrary key/value.

Public API:
    upsert_job(...)              — insert or update a job row
    add_alias(canon_key, alias)  — record a name variant
    set_link(canon_key, type, value) — add a link reference
    get_link / get_links         — read a link / all links of a type
    remove_link                  — drop a specific link
    find_job_by_name(name)       — canonicalize + alias-fallback lookup
    find_jobs_by_status(status)  — status filter
    iter_jobs()                  — every job, newest-first
    log_event(canon_key, type)   — write an audit-trail entry
    export_db(path)              — write a portable JSON snapshot
    import_db(path, mode=...)    — read a JSON snapshot back in
    sync_from_trello()           — refresh jobs from in-scope boards
    canon_key(name)              — same canonicalizer persistence uses
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable

import paths as _paths

# ── Shared logic ────────────────────────────────────────────────────────
# Identity + classification live in ems_db_common so this backend and the
# Supabase one cannot drift. canon_key IS a job's identity; two backends
# disagreeing on it would silently split one job into two.
from ems_db_common import (            # noqa: E402  (after module docstring)
    _UNIT_DETECT_PATTERNS, detect_property_and_unit, canon_key,
    LINK_FOLDER, LINK_TRELLO, LINK_COMPANYCAM, _STRONG_LINK_TYPES,
    _norm_link, invalidate_department_cache, department_for_path,
    split_department_path, rebase_department_path,
    CHILD_CLAIM, CHILD_UNIT, CHILD_SUBJOB, classify_child, _now_iso,
)
from persistence import _canon_pin_key as _canon_pin_key_persistence


# Single canonical DB path — sits alongside persistence.json under
# %APPDATA%\Linguar Hub\ so coworkers find both files in the same
# place when they need to back the suite up or migrate machines.
DB_PATH = _paths.data("ems_jobs.db")

SCHEMA_VERSION = 4





# Serialize all writes through one lock — SQLite handles read concurrency
# fine but write contention from multiple panels on the same process can
# race. The connection itself is opened per-call so threads each get
# their own (sqlite3 module objects aren't safely shared across threads).
_LOCK = threading.RLock()


# ── Canonicalization ────────────────────────────────────────────────────



# ── Connection / schema ─────────────────────────────────────────────────

@contextmanager
def _connect():
    """Yield a connection in the current thread. Foreign keys are
    enabled per-connection (SQLite default-off). WAL mode is set once
    at schema-init time so concurrent readers don't block writers."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def _init_schema():
    """Idempotent — safe to call on every module import. Bumps
    meta.schema_version after a successful create so future migrations
    can branch on it."""
    with _LOCK, _connect() as c:
        c.executescript("""
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS jobs (
                canon_key       TEXT PRIMARY KEY,
                display_name    TEXT NOT NULL,
                claim_number    TEXT,
                carrier         TEXT,
                loss_type       TEXT,
                year            INTEGER,
                status          TEXT,
                date_received   TEXT,
                first_seen_at   TEXT,
                last_seen_at    TEXT,
                metadata_json   TEXT,
                parent_canon    TEXT,
                unit_number     TEXT,
                department      TEXT
            );
            -- idx_jobs_parent is created after the upgrade-friendly
            -- ALTER TABLE block below, since older v1 installs need
            -- the column added before the index can target it.

            CREATE TABLE IF NOT EXISTS job_aliases (
                canon_key       TEXT NOT NULL,
                alias           TEXT NOT NULL,
                alias_canon     TEXT NOT NULL,
                source          TEXT,
                added_at        TEXT,
                PRIMARY KEY (canon_key, alias_canon),
                FOREIGN KEY (canon_key)
                    REFERENCES jobs(canon_key) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_aliases_canon
                ON job_aliases(alias_canon);

            CREATE TABLE IF NOT EXISTS job_links (
                canon_key       TEXT NOT NULL,
                link_type       TEXT NOT NULL,
                link_value      TEXT NOT NULL,
                added_at        TEXT,
                added_by        TEXT,
                metadata_json   TEXT,
                PRIMARY KEY (canon_key, link_type, link_value),
                FOREIGN KEY (canon_key)
                    REFERENCES jobs(canon_key) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_links_key
                ON job_links(canon_key);

            CREATE TABLE IF NOT EXISTS job_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                canon_key       TEXT NOT NULL,
                event_type      TEXT NOT NULL,
                event_at        TEXT NOT NULL,
                payload_json    TEXT,
                FOREIGN KEY (canon_key)
                    REFERENCES jobs(canon_key) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_events_key
                ON job_events(canon_key);

            -- v4: children of a client — the second claim, the unit, the
            -- commercial sub-job. `year → client → child` is one shape, so
            -- this is one table; only `kind` differs.
            --
            -- Replaces jobs.parent_canon / jobs.unit_number, which inferred
            -- the hierarchy from NAME STRINGS and got it wrong: on live
            -- data all 21 rows carrying a parent_canon pointed at a parent
            -- that does not exist ('store', 'stater bros', 'monterey
            -- apartments ga'). Rows here exist because a child FOLDER
            -- exists — disk is the authority, same rule as jobs.department.
            --
            -- trello_card is the point of the table: a client with several
            -- claims or units has several cards (live data has jobs with 7,
            -- 8 and 12), and the flat job_links list cannot say which card
            -- belongs to which child.
            CREATE TABLE IF NOT EXISTS job_children (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_canon  TEXT NOT NULL,
                name          TEXT NOT NULL,
                kind          TEXT NOT NULL,      -- claim | unit | subjob
                ordinal       INTEGER,            -- claim number, if a claim
                folder_path   TEXT,
                trello_card   TEXT,
                companycam    TEXT,
                department    TEXT,
                created_at    TEXT,
                updated_at    TEXT,
                UNIQUE (parent_canon, name)
            );
            CREATE INDEX IF NOT EXISTS idx_children_parent
                ON job_children(parent_canon);
            CREATE INDEX IF NOT EXISTS idx_children_folder
                ON job_children(folder_path);
            CREATE INDEX IF NOT EXISTS idx_children_card
                ON job_children(trello_card);

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            -- Pipeline / lifecycle tracker (one row per Trello card).
            -- Populated by pipeline_stages.sync_workspace(). Cheap to
            -- query for the Pipeline panel + per-card stage chip on
            -- existing rows (audit / Hygiene). Stage transitions are
            -- detected on each sync: if current_stage changed from the
            -- previous sync, stage_entered_at gets bumped to "now" so
            -- "days in stage" is honest. We don't track full history
            -- in this table yet — Phase 2 adds a separate transitions
            -- log if needed.
            CREATE TABLE IF NOT EXISTS job_lifecycle (
                card_id           TEXT PRIMARY KEY,
                client_canon      TEXT,
                client_display    TEXT,
                board_id          TEXT,
                board_name        TEXT,
                list_id           TEXT,
                list_name         TEXT,
                current_stage     TEXT,
                stage_entered_at  TEXT,
                created_at        TEXT,
                last_activity_at  TEXT,
                billed_at         TEXT,
                paid_at           TEXT,
                card_url          TEXT,
                owner             TEXT,
                updated_at        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_lifecycle_stage
                ON job_lifecycle(current_stage);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_client
                ON job_lifecycle(client_canon);

            -- Pipeline stage transition log (one row per stage change).
            -- Driven by lifecycle_upsert: when current_stage changes,
            -- we record the OLD stage as from_stage, the new one as
            -- to_stage, and the days the card spent in the old stage.
            -- That gives KPI metrics a real population for cycle-time
            -- distributions, instead of inferring from current-state
            -- median (which only sees the active backlog).
            CREATE TABLE IF NOT EXISTS job_stage_transitions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id             TEXT NOT NULL,
                client_canon        TEXT,
                from_stage          TEXT,
                to_stage            TEXT NOT NULL,
                transitioned_at     TEXT NOT NULL,
                days_in_from_stage  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_transitions_card
                ON job_stage_transitions(card_id);
            CREATE INDEX IF NOT EXISTS idx_transitions_from
                ON job_stage_transitions(from_stage);
        """)
        # Idempotent column adds — for upgrade-from-v1 installs the
        # CREATE TABLE IF NOT EXISTS above was a no-op, so any new
        # columns need an explicit ALTER. SQLite raises on duplicate
        # column add; swallow that one specific error.
        for col_sql in (
            "ALTER TABLE jobs ADD COLUMN parent_canon TEXT",
            "ALTER TABLE jobs ADD COLUMN unit_number TEXT",
            # v3: which franchise OWNS this job. NULL = unknown, and
            # unknown stays permissive everywhere — the column guards
            # against cross-wiring, it does not gate lookups.
            "ALTER TABLE jobs ADD COLUMN department TEXT",
            # Pipeline Phase 4: track which lifecycle rows have been
            # backfilled from Trello card-action history (gives the
            # honest "days in stage" instead of the dateLastActivity
            # proxy). NULL = not yet enriched.
            "ALTER TABLE job_lifecycle ADD COLUMN actions_synced_at TEXT",
        ):
            try:
                c.execute(col_sql)
            except sqlite3.OperationalError as ex:
                if "duplicate column" not in str(ex).lower():
                    raise
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_canon)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_department ON jobs(department)")
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                   ("schema_version", str(SCHEMA_VERSION)))
        c.commit()


def reset_db_path(new_path: str) -> None:
    """Override DB_PATH at runtime (for tests). Re-initializes schema
    against the new file. Production code should never call this."""
    global DB_PATH
    DB_PATH = new_path
    _init_schema()


# ── Helpers ─────────────────────────────────────────────────────────────



def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    md = d.pop("metadata_json", None)
    if md:
        try:
            d["metadata"] = json.loads(md)
        except (TypeError, ValueError):
            d["metadata"] = {}
    return d






class DepartmentConflict(Exception):
    """Raised when an operation would tie one franchise's data to another
    franchise's job. Always a data question for a human — never something
    to auto-resolve, because both silent outcomes (merge, or overwrite the
    owner) corrupt one of the two jobs."""














def department_of_job(canon_key_value: str) -> str | None:
    """The stored department for a job, or None when unknown."""
    job = get_job(canon_key_value)
    return (job or {}).get("department") or None


def set_department(canon_key_value: str, department: str, *,
                   overwrite: bool = False) -> bool:
    """Stamp a job's owning department. By default only fills a NULL —
    pass overwrite=True to correct a wrong one. Returns True if written."""
    dept = (department or "").strip()
    if not (canon_key_value and dept):
        return False
    with _LOCK, _connect() as c:
        row = c.execute("SELECT department FROM jobs WHERE canon_key=?",
                        (canon_key_value,)).fetchone()
        if row is None:
            return False
        if row["department"] and not overwrite:
            return False
        c.execute("UPDATE jobs SET department=? WHERE canon_key=?",
                  (dept, canon_key_value))
        c.commit()
    return True


def _department_conflict(job: dict | None, incoming_dept: str | None) -> bool:
    """True when a job already belongs to a DIFFERENT franchise than the
    one implied by an incoming folder. Unknown on either side never
    conflicts."""
    if not job or not incoming_dept:
        return False
    have = (job.get("department") or "").strip()
    return bool(have) and have != incoming_dept


# ── Write API ───────────────────────────────────────────────────────────

def upsert_job(*, display_name: str,
                claim_number: str = "",
                carrier: str = "",
                loss_type: str = "",
                year: int | None = None,
                status: str = "",
                date_received: str = "",
                department: str = "",
                metadata: dict | None = None) -> str:
    """Insert or update a job, keyed on `canon_key(display_name)`.

    Fields are partial-update: a blank value passed in does NOT
    overwrite an existing non-blank value. That way Trello sync can
    refresh display_name + status without nuking the loss_type a
    different tool already filled in.

    Returns the canon_key.
    """
    key = canon_key(display_name)
    if not key:
        raise ValueError("display_name must canonicalize to a non-empty key")
    now = _now_iso()
    md_json = json.dumps(metadata) if metadata else None
    # DEPRECATED (v4): parent_canon / unit_number used to be inferred from
    # the display name here on every upsert. That inference was wrong — on
    # live data every one of the 21 rows it had populated pointed at a
    # parent that does not exist ('store', 'stater bros', 'monterey
    # apartments ga'), because a name is not a hierarchy. `job_children`
    # replaces it, built from the folder tree. The columns stay so older
    # readers don't break, but nothing writes them implicitly any more.
    parent_canon_value = None
    unit_num = None
    with _LOCK, _connect() as c:
        existing = c.execute(
            "SELECT * FROM jobs WHERE canon_key = ?", (key,)).fetchone()
        if existing is None:
            c.execute("""
                INSERT INTO jobs
                    (canon_key, display_name, claim_number, carrier,
                     loss_type, year, status, date_received,
                     first_seen_at, last_seen_at, metadata_json,
                     parent_canon, unit_number, department)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, display_name, claim_number, carrier, loss_type,
                  year, status, date_received, now, now, md_json,
                  parent_canon_value, unit_num,
                  (department or "").strip() or None))
        else:
            # Partial-update: only overwrite columns the caller actually
            # supplied (non-empty). display_name is always overwritten
            # so casing/spacing fixes propagate.
            new_vals = {
                "display_name":  display_name or existing["display_name"],
                "claim_number":  claim_number or existing["claim_number"],
                "carrier":       carrier      or existing["carrier"],
                "loss_type":     loss_type    or existing["loss_type"],
                "year":          year         if year is not None else existing["year"],
                "status":        status       or existing["status"],
                "date_received": date_received or existing["date_received"],
                "last_seen_at":  now,
                "metadata_json": md_json      or existing["metadata_json"],
            }
            # Re-detect on every upsert: if the display_name changed
            # (e.g. a rename in Trello), the parent/unit derivation
            # should follow. Partial-update rule: keep the existing
            # parent_canon if the new detection comes up blank.
            new_parent = parent_canon_value or existing["parent_canon"]
            new_unit   = unit_num or existing["unit_number"]
            # Department follows the same partial-update rule: a blank
            # never clears an established owner. Correcting a wrong one
            # is an explicit set_department(overwrite=True).
            new_dept = ((department or "").strip()
                        or existing["department"] or None)
            c.execute("""
                UPDATE jobs SET
                    display_name=?, claim_number=?, carrier=?, loss_type=?,
                    year=?, status=?, date_received=?, last_seen_at=?,
                    metadata_json=?, parent_canon=?, unit_number=?,
                    department=?
                WHERE canon_key=?
            """, (new_vals["display_name"], new_vals["claim_number"],
                  new_vals["carrier"], new_vals["loss_type"],
                  new_vals["year"], new_vals["status"],
                  new_vals["date_received"], new_vals["last_seen_at"],
                  new_vals["metadata_json"], new_parent, new_unit,
                  new_dept, key))
        c.commit()
    return key


def add_alias(canon_key_value: str, alias: str, *,
              source: str = "manual") -> None:
    """Record a name variant for a job. Idempotent — re-adding the
    same alias is a no-op. The alias's own canonicalization is
    indexed so `find_job_by_name` can match either form."""
    if not canon_key_value or not alias:
        return
    alias_canon = canon_key(alias)
    if not alias_canon or alias_canon == canon_key_value:
        # Self-alias (same canon as the primary) is meaningless to store.
        return
    with _LOCK, _connect() as c:
        c.execute("""
            INSERT OR IGNORE INTO job_aliases
                (canon_key, alias, alias_canon, source, added_at)
            VALUES (?, ?, ?, ?, ?)
        """, (canon_key_value, alias, alias_canon, source, _now_iso()))
        c.commit()


def set_link(canon_key_value: str, link_type: str, link_value: str, *,
             metadata: dict | None = None,
             added_by: str = "") -> None:
    """Add a link from a job into an external system. Idempotent —
    repeat calls with the same (job, type, value) update `metadata`
    + `added_at` without duplicating. Pass `remove_link()` to drop."""
    # Normalize strong-identifier values so a folder path or Trello URL
    # written by one tool matches a lookup done by another.
    if link_type in _STRONG_LINK_TYPES:
        link_value = _norm_link(link_type, link_value)
    if not (canon_key_value and link_type and link_value):
        return
    md_json = json.dumps(metadata) if metadata else None
    with _LOCK, _connect() as c:
        c.execute("""
            INSERT INTO job_links
                (canon_key, link_type, link_value, added_at, added_by, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(canon_key, link_type, link_value) DO UPDATE SET
                added_at=excluded.added_at,
                added_by=excluded.added_by,
                metadata_json=excluded.metadata_json
        """, (canon_key_value, link_type, link_value,
              _now_iso(), added_by, md_json))
        # A folder pin is the one signal that says which franchise owns
        # this job, so learn it here — every surface that pins a folder
        # gets department stamping for free. Fills NULL only; a job that
        # already has an owner is never silently reassigned.
        if link_type == LINK_FOLDER:
            dept = department_for_path(link_value)
            if dept:
                c.execute("UPDATE jobs SET department=? "
                          "WHERE canon_key=? AND "
                          "(department IS NULL OR department='')",
                          (dept, canon_key_value))
        c.commit()


def remove_link(canon_key_value: str, link_type: str,
                link_value: str = "") -> None:
    """Drop a link. Blank `link_value` removes ALL links of the
    given type for the job (handy when nuking a stale type).

    Strong-identifier values are normalized on the way IN by set_link, so
    they must be normalized here too. Without it, removing a folder by its
    natural mixed-case path compares against the stored lowercase form,
    matches nothing, and returns as though it worked — which is how a
    wrong folder stayed attached to a job after being "unpinned".
    """
    if not (canon_key_value and link_type):
        return
    if link_value and link_type in _STRONG_LINK_TYPES:
        link_value = _norm_link(link_type, link_value)
    with _LOCK, _connect() as c:
        if link_value:
            c.execute("""
                DELETE FROM job_links
                WHERE canon_key=? AND link_type=? AND link_value=?
            """, (canon_key_value, link_type, link_value))
        else:
            c.execute("""
                DELETE FROM job_links
                WHERE canon_key=? AND link_type=?
            """, (canon_key_value, link_type))
        c.commit()


def merge_jobs(into_key: str, from_keys) -> dict:
    """Fold each job in `from_keys` INTO `into_key`: move their aliases +
    links onto `into_key`, record their display name as an alias, then
    delete the redundant job rows. Used by the pin→card reconciliation to
    collapse many differently-spelled duplicates of one job into a single
    canonical (Trello-card-named) job. `into_key` MUST already exist in
    `jobs` (caller upserts the canonical job first). Idempotent: a
    from_key that equals into_key or no longer exists is skipped."""
    into_key = (into_key or "").strip()
    if not into_key:
        return {"merged": 0}
    merged = 0
    skipped_dept = []
    with _LOCK, _connect() as c:
        into_dept = (c.execute(
            "SELECT department FROM jobs WHERE canon_key=?",
            (into_key,)).fetchone() or {"department": None})["department"]
        for fk in from_keys or ():
            fk = (fk or "").strip()
            if not fk or fk == into_key:
                continue
            row = c.execute(
                "SELECT display_name, department FROM jobs WHERE canon_key = ?",
                (fk,)).fetchone()
            # Two jobs owned by different franchises are never the same
            # job, however similar their names. Skip rather than fold —
            # a merge here is unrecoverable.
            if (row is not None and into_dept and row["department"]
                    and row["department"] != into_dept):
                skipped_dept.append(fk)
                continue
            # Move aliases (skip PK collisions), then drop leftovers.
            c.execute("UPDATE OR IGNORE job_aliases SET canon_key=? "
                      "WHERE canon_key=?", (into_key, fk))
            c.execute("DELETE FROM job_aliases WHERE canon_key=?", (fk,))
            # Move links the same way.
            c.execute("UPDATE OR IGNORE job_links SET canon_key=? "
                      "WHERE canon_key=?", (into_key, fk))
            c.execute("DELETE FROM job_links WHERE canon_key=?", (fk,))
            c.execute("DELETE FROM job_events WHERE canon_key=?", (fk,))
            # Preserve the old spelling as a searchable alias of the winner.
            if row and row["display_name"]:
                ac = canon_key(row["display_name"])
                if ac and ac != into_key:
                    c.execute(
                        "INSERT OR IGNORE INTO job_aliases "
                        "(canon_key, alias, alias_canon, source, added_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (into_key, row["display_name"], ac, "merge",
                         _now_iso()))
            c.execute("DELETE FROM jobs WHERE canon_key=?", (fk,))
            if row is not None:
                merged += 1
        # Drop any self-alias that snuck in (alias canonicalizes to itself).
        c.execute("DELETE FROM job_aliases WHERE canon_key=? "
                  "AND alias_canon=?", (into_key, into_key))
        c.commit()
    out = {"merged": merged}
    if skipped_dept:
        out["skipped_department_conflict"] = skipped_dept
    return out


def backfill_departments(*, overwrite: bool = False) -> dict:
    """Stamp `department` on every job we can identify, from its folder
    links. Idempotent and re-runnable.

    Only folder roots are consulted — see the module note on why the Trello
    board can't be used. A job whose folders span two departments is left
    alone and reported under "conflicts": that's real data corruption (or a
    mis-pin) and needs a person, not a guess.

    Returns {"stamped": N, "already": N, "unknown": N, "conflicts": [...]}.
    """
    stamped = already = unknown = 0
    conflicts = []
    with _LOCK, _connect() as c:
        rows = c.execute(
            "SELECT canon_key, display_name, department FROM jobs").fetchall()
        for r in rows:
            key = r["canon_key"]
            if r["department"] and not overwrite:
                already += 1
                continue
            folders = [x["link_value"] for x in c.execute(
                "SELECT link_value FROM job_links "
                "WHERE canon_key=? AND link_type=?",
                (key, LINK_FOLDER)).fetchall()]
            depts = {d for d in (department_for_path(f) for f in folders) if d}
            if not depts:
                unknown += 1
                continue
            if len(depts) > 1:
                conflicts.append({"canon_key": key,
                                  "display_name": r["display_name"],
                                  "departments": sorted(depts),
                                  "folders": folders})
                continue
            c.execute("UPDATE jobs SET department=? WHERE canon_key=?",
                      (depts.pop(), key))
            stamped += 1
        c.commit()
    return {"stamped": stamped, "already": already,
            "unknown": unknown, "conflicts": conflicts}


def find_dead_folder_links() -> list[dict]:
    """Folder links whose path no longer exists on disk.

    They accumulate whenever a folder is renamed or merged outside the app
    — the old link just sits there. Harmless on their own, but they make a
    job look like it owns two folders, which is what the duplicate-folder
    report keys on, so stale links generate false alarms.

    Read-only. Returns [{canon_key, display_name, path}].
    """
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
    """Drop every folder link whose path is gone.

    Only run this with the share REACHABLE — an unreachable X: makes every
    path look dead and would wipe the lot.
    """
    dead = find_dead_folder_links()
    for d in dead:
        remove_link(d["canon_key"], LINK_FOLDER, d["path"])
    return {"removed": len(dead), "links": dead}


def find_department_conflicts() -> list[dict]:
    """Jobs whose folder links span more than one franchise, or whose
    stored department contradicts its folders. Empty = clean."""
    out = []
    with _LOCK, _connect() as c:
        rows = c.execute(
            "SELECT canon_key, display_name, department FROM jobs").fetchall()
        for r in rows:
            folders = [x["link_value"] for x in c.execute(
                "SELECT link_value FROM job_links "
                "WHERE canon_key=? AND link_type=?",
                (r["canon_key"], LINK_FOLDER)).fetchall()]
            depts = {d for d in (department_for_path(f) for f in folders) if d}
            if not depts:
                continue
            stored = (r["department"] or "").strip()
            if len(depts) > 1 or (stored and stored not in depts):
                out.append({"canon_key": r["canon_key"],
                            "display_name": r["display_name"],
                            "stored": stored or None,
                            "folder_departments": sorted(depts),
                            "folders": folders})
    return out


def count_by_department() -> dict:
    """{dept_or_'unknown': count} across all jobs."""
    out = {}
    with _LOCK, _connect() as c:
        for r in c.execute(
                "SELECT COALESCE(NULLIF(department,''),'unknown') AS d, "
                "COUNT(*) AS n FROM jobs GROUP BY d ORDER BY n DESC"):
            out[r["d"]] = r["n"]
    return out


def log_event(canon_key_value: str, event_type: str, *,
              payload: dict | None = None) -> None:
    """Append an event to the audit trail. Per-machine — events are
    NOT included in export_db output."""
    if not (canon_key_value and event_type):
        return
    pj = json.dumps(payload) if payload else None
    with _LOCK, _connect() as c:
        c.execute("""
            INSERT INTO job_events
                (canon_key, event_type, event_at, payload_json)
            VALUES (?, ?, ?, ?)
        """, (canon_key_value, event_type, _now_iso(), pj))
        c.commit()


# ── Read API ────────────────────────────────────────────────────────────

def find_job_by_name(name: str, *, department: str = "") -> dict | None:
    """Resolve a job from any spelling we've seen. Tries:
      1. Direct canon_key match on `jobs.canon_key`.
      2. Alias canon match on `job_aliases.alias_canon`.
    Returns the job dict (with `metadata` parsed) or None.

    `department` is OPT-IN and defaults to unscoped on purpose. IE staff
    work OC's recon jobs, so scoping every lookup to the active department
    would hide jobs people legitimately need. Pass it only where a wrong-
    franchise match would be harmful (writes), not for plain lookups. A job
    with no department recorded matches either way.
    """
    if not name:
        return None
    key = canon_key(name)
    if not key:
        return None
    dept = (department or "").strip()
    with _LOCK, _connect() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE canon_key=?", (key,)).fetchone()
        if row is None:
            row = c.execute("""
                SELECT j.* FROM jobs j
                JOIN job_aliases a ON a.canon_key = j.canon_key
                WHERE a.alias_canon = ?
                LIMIT 1
            """, (key,)).fetchone()
        if row is not None and dept:
            have = (row["department"] or "").strip()
            if have and have != dept:
                return None
        return _row_to_dict(row)


def card_display_names_for(names) -> dict:
    """Bulk form of "what does this job's pinned Trello card call it?".

    Returns {input_name: display_name} for every name that resolves to a job
    which (a) has a display_name and (b) has a trello_card link — the exact
    condition the audit row shaper applies one row at a time.

    Two queries total, regardless of row count. The per-row version costs
    two round trips PER ROW; on a 300-row audit that is ~600 queries, which
    is invisible against local SQLite and fatal against a hosted database.
    Resolution order matches find_job_by_name: direct canon_key first, then
    alias, so a name that is both wins the same way it would singly.
    """
    wanted = {}
    for n in names or ():
        k = canon_key(n or "")
        if k:
            wanted.setdefault(k, []).append(n)
    if not wanted:
        return {}
    keys = list(wanted)
    marks = ",".join("?" * len(keys))
    out = {}
    with _LOCK, _connect() as c:
        # Pass 1 — direct canon_key hits. Fetch EVERY direct match, not
        # just carded ones: find_job_by_name stops at the direct hit and
        # never consults aliases, so a name that is its own job must not
        # fall through to pass 2 merely because that job has no card.
        # (Live data: 'Gabriel Ramirez' is a real uncarded job AND an alias
        # of the carded 'Ramirez, Gabriella - Farmers'. Falling through
        # renamed the row to a different customer.)
        rows = c.execute(f"""
            SELECT j.canon_key, j.display_name,
                   EXISTS (SELECT 1 FROM job_links l
                           WHERE l.canon_key = j.canon_key
                             AND l.link_type = ?) AS has_card
            FROM jobs j
            WHERE j.canon_key IN ({marks})
        """, (LINK_TRELLO, *keys)).fetchall()
        direct = set()
        for r in rows:
            direct.add(r["canon_key"])
            if r["has_card"] and (r["display_name"] or ""):
                for orig in wanted.get(r["canon_key"], ()):
                    out[orig] = r["display_name"]
        # Pass 2 — alias hits, ONLY for names with no direct job row.
        left = [k for k in keys if k not in direct]
        if left:
            marks2 = ",".join("?" * len(left))
            rows = c.execute(f"""
                SELECT a.alias_canon, j.display_name
                FROM jobs j
                JOIN job_aliases a ON a.canon_key = j.canon_key
                WHERE a.alias_canon IN ({marks2})
                  AND j.display_name IS NOT NULL AND j.display_name <> ''
                  AND EXISTS (SELECT 1 FROM job_links l
                              WHERE l.canon_key = j.canon_key
                                AND l.link_type = ?)
            """, (*left, LINK_TRELLO)).fetchall()
            for r in rows:
                for orig in wanted.get(r["alias_canon"], ()):
                    out.setdefault(orig, r["display_name"])
    return out


def get_job(canon_key_value: str) -> dict | None:
    """Fetch a job row by its canon_key. None when absent."""
    if not canon_key_value:
        return None
    with _LOCK, _connect() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE canon_key=?", (canon_key_value,)).fetchone()
    return _row_to_dict(row)


def _is_primary_job_key(key: str) -> bool:
    """True when `key` is the canon_key of a real job row (not just a bare
    spelling). Guards resolve_and_link from cross-wiring two distinct jobs."""
    if not key:
        return False
    with _LOCK, _connect() as c:
        return c.execute(
            "SELECT 1 FROM jobs WHERE canon_key=? LIMIT 1", (key,)
        ).fetchone() is not None


def find_job_by_link(link_type: str, link_value: str) -> dict | None:
    """Reverse lookup: the job that owns a given external reference (OD
    folder / Trello card / CompanyCam project). This is what proves two
    different name spellings are the same job. Returns the job dict or None."""
    nv = _norm_link(link_type, link_value)
    if not (link_type and nv):
        return None
    with _LOCK, _connect() as c:
        row = c.execute("""
            SELECT j.* FROM jobs j
            JOIN job_links l ON l.canon_key = j.canon_key
            WHERE l.link_type=? AND l.link_value=?
            ORDER BY l.added_at ASC
            LIMIT 1
        """, (link_type, nv)).fetchone()
    return _row_to_dict(row)


def resolve_and_link(name: str = "", *, folder_path: str = "",
                     trello_card: str = "", companycam_project: str = "",
                     create: bool = False, source: str = "auto",
                     display_name: str = "",
                     strict_department: bool = True) -> dict | None:
    """Resolve a job to ONE canonical identity and auto-teach aliases so
    every tool converges on the same job instead of re-guessing by name.

    Strong identifiers (folder_path / trello_card / companycam_project) are
    ground truth. If any of them already belongs to a job, THAT job wins and
    the incoming `name` spelling is recorded as an alias — so the next tool
    that passes this spelling resolves to the same job via find_job_by_name().
    When only the name resolves, any supplied strong links get attached to it,
    tying the systems together for the next lookup.

    `create=True` upserts a new job (from `display_name` or `name`) when
    nothing matches. Never cross-wires two REAL jobs — if the incoming name is
    itself a distinct job, it's left alone (that's a merge, handled elsewhere).

    **Cross-franchise guard:** when `folder_path` sits under one department's
    root and the job the NAME resolved to belongs to a different department,
    the two are different jobs that happen to share a customer name — the
    match is rejected rather than linked. `strict_department=False` opts out.
    Note the guard applies to name matches only: a folder/card/CompanyCam hit
    is a proven identity, and a Trello card carries no franchise information
    at all (IE runs recon for OC jobs on IE boards).

    Returns the resolved job dict, or None when unresolved and create=False.
    Raises DepartmentConflict when the resolved job's owner contradicts the
    incoming folder's — the caller must disambiguate rather than merge.
    """
    name = (name or "").strip()
    strong = [(LINK_FOLDER, folder_path),
              (LINK_TRELLO, trello_card),
              (LINK_COMPANYCAM, companycam_project)]
    incoming_dept = department_for_path(folder_path) if folder_path else None

    job = None
    for lt, lv in strong:            # strong links prove identity first
        if lv:
            job = find_job_by_link(lt, lv)
            if job:
                break
    if job is not None and strict_department and _department_conflict(
            job, incoming_dept):
        # The folder itself already belongs to a job owned by the other
        # franchise. Never seen in practice; if it happens the data is
        # wrong in a way only a human should resolve.
        raise DepartmentConflict(
            f"folder {folder_path!r} is under the {incoming_dept} root but "
            f"is already linked to {job['canon_key']!r}, owned by "
            f"{job.get('department')}")
    if job is None and name:         # fall back to name / existing alias
        job = find_job_by_name(name)
        if job is not None and strict_department and _department_conflict(
                job, incoming_dept):
            # Same customer name in both franchises — the classic silent
            # merge. Treat it as no match so a distinct job is created.
            job = None
    if job is None:                  # nothing matched
        if not create:
            return None
        dn = (display_name or name).strip()
        if not dn:
            return None
        # Creating would key on canon_key(dn) — which may already be the
        # OTHER franchise's job. One key space means we cannot hold two
        # same-named jobs in different departments, so refuse loudly
        # instead of quietly taking over their row.
        clash = get_job(canon_key(dn))
        if strict_department and _department_conflict(clash, incoming_dept):
            raise DepartmentConflict(
                f"{dn!r} already exists as a {clash.get('department')} job; "
                f"the incoming folder is {incoming_dept}. Rename one of them "
                f"(e.g. add the carrier or claim #) so the two franchises' "
                f"jobs stay distinct.")
        key = upsert_job(display_name=dn, department=incoming_dept or "")
        job = get_job(key)
        if job is None:
            return None

    key = job["canon_key"]
    # Teach the incoming spelling as an alias of this job — unless it's
    # itself a distinct real job (don't merge silently).
    if name:
        nk = canon_key(name)
        if nk and nk != key and not _is_primary_job_key(nk):
            add_alias(key, name, source=source)
    # Tie the supplied strong links to this job (idempotent + normalized).
    for lt, lv in strong:
        if lv:
            set_link(key, lt, lv, added_by=source)
    return get_job(key)


def get_link(canon_key_value: str, link_type: str) -> str | None:
    """First (oldest) link of `link_type` for the job, or None."""
    if not (canon_key_value and link_type):
        return None
    with _LOCK, _connect() as c:
        row = c.execute("""
            SELECT link_value FROM job_links
            WHERE canon_key=? AND link_type=?
            ORDER BY added_at ASC
            LIMIT 1
        """, (canon_key_value, link_type)).fetchone()
    return row["link_value"] if row else None


def get_links(canon_key_value: str, link_type: str = "") -> list[dict]:
    """All links for a job (optionally filtered by type), newest-first."""
    if not canon_key_value:
        return []
    with _LOCK, _connect() as c:
        if link_type:
            rows = c.execute("""
                SELECT * FROM job_links
                WHERE canon_key=? AND link_type=?
                ORDER BY added_at DESC
            """, (canon_key_value, link_type)).fetchall()
        else:
            rows = c.execute("""
                SELECT * FROM job_links
                WHERE canon_key=?
                ORDER BY added_at DESC
            """, (canon_key_value,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def job_identity(name: str) -> dict | None:
    """Everything tied to the job that `name` resolves to: the canonical
    row, its learned aliases (list of spelling strings), and all external
    links (folder / Trello / CompanyCam). None when the name resolves to no
    known job. Read-only — the single 'what's tied together?' view."""
    job = find_job_by_name(name)
    if not job:
        return None
    key = job["canon_key"]
    return {
        "job": job,
        "aliases": get_aliases(key),   # -> list[str]
        "links": get_links(key),
    }


def find_jobs_by_status(status: str) -> list[dict]:
    """Every job matching a status string (e.g. 'new_loss'),
    newest-seen first."""
    if not status:
        return []
    with _LOCK, _connect() as c:
        rows = c.execute("""
            SELECT * FROM jobs
            WHERE status=?
            ORDER BY last_seen_at DESC
        """, (status,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def iter_jobs() -> list[dict]:
    """Every job, newest-seen first. Cheap — table is small."""
    with _LOCK, _connect() as c:
        rows = c.execute("""
            SELECT * FROM jobs ORDER BY last_seen_at DESC
        """).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Children of a client (claims / units / commercial sub-jobs) ────────
# `year → client → child` is ONE shape; only `kind` differs. Rows come
# from the folder tree, never from parsing a name.






def set_child(parent_canon: str, name: str, *, kind: str = "",
              ordinal=None, folder_path: str = "", trello_card: str = "",
              companycam: str = "", department: str = "") -> dict:
    """Record (or update) one child of a client. Idempotent on
    (parent_canon, name); blank values never overwrite existing ones —
    the same partial-update rule as upsert_job."""
    parent_canon = (parent_canon or "").strip()
    name = (name or "").strip()
    if not (parent_canon and name):
        return {}
    if not kind:
        kind, ordinal = classify_child(name)
    fp = _norm_link(LINK_FOLDER, folder_path) if folder_path else ""
    card = _norm_link(LINK_TRELLO, trello_card) if trello_card else ""
    now = _now_iso()
    with _LOCK, _connect() as c:
        row = c.execute("SELECT * FROM job_children WHERE parent_canon=? "
                        "AND name=?", (parent_canon, name)).fetchone()
        if row is None:
            c.execute("""
                INSERT INTO job_children
                    (parent_canon, name, kind, ordinal, folder_path,
                     trello_card, companycam, department, created_at,
                     updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (parent_canon, name, kind, ordinal, fp, card,
                  companycam, department, now, now))
        else:
            c.execute("""
                UPDATE job_children SET
                    kind=?, ordinal=?, folder_path=?, trello_card=?,
                    companycam=?, department=?, updated_at=?
                WHERE parent_canon=? AND name=?
            """, (kind or row["kind"],
                  ordinal if ordinal is not None else row["ordinal"],
                  fp or row["folder_path"], card or row["trello_card"],
                  companycam or row["companycam"],
                  department or row["department"], now,
                  parent_canon, name))
        c.commit()
        out = c.execute("SELECT * FROM job_children WHERE parent_canon=? "
                        "AND name=?", (parent_canon, name)).fetchone()
    return dict(out) if out else {}


def all_children() -> list:
    """Every child row, in ONE query — for the type-ahead index.

    Children are where units and commercial sub-jobs live, and they are
    the names people actually search for ("Unit 418", "Eastvale"). Walking
    children_of() per client would be 41 round trips here and the same
    N+1 on the hosted backend.
    """
    with _LOCK, _connect() as c:
        rows = c.execute(
            "SELECT * FROM job_children "
            "ORDER BY parent_canon, COALESCE(ordinal, 9999), name").fetchall()
    return [dict(r) for r in rows]


def children_of(parent_canon: str, *, kind: str = "") -> list:
    """Every child of a client, optionally filtered by kind. Claims sort
    by ordinal, everything else by name."""
    parent_canon = (parent_canon or "").strip()
    if not parent_canon:
        return []
    sql = "SELECT * FROM job_children WHERE parent_canon=?"
    args = [parent_canon]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    sql += " ORDER BY COALESCE(ordinal, 9999), name"
    with _LOCK, _connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def find_child_by_folder(folder_path: str):
    """The child a folder belongs to — tells a pinned unit folder which
    client it sits under."""
    fp = _norm_link(LINK_FOLDER, folder_path)
    if not fp:
        return None
    with _LOCK, _connect() as c:
        r = c.execute("SELECT * FROM job_children WHERE folder_path=? "
                      "LIMIT 1", (fp,)).fetchone()
    return dict(r) if r else None


def find_child_by_card(trello_card: str):
    """Which child a Trello card belongs to — the question the flat
    job_links list could never answer."""
    card = _norm_link(LINK_TRELLO, trello_card)
    if not card:
        return None
    with _LOCK, _connect() as c:
        r = c.execute("SELECT * FROM job_children WHERE trello_card=? "
                      "LIMIT 1", (card,)).fetchone()
    return dict(r) if r else None


def remove_child(parent_canon: str, name: str) -> bool:
    with _LOCK, _connect() as c:
        cur = c.execute("DELETE FROM job_children WHERE parent_canon=? "
                        "AND name=?", ((parent_canon or "").strip(),
                                       (name or "").strip()))
        c.commit()
    return cur.rowcount > 0


def find_units_of(parent_canon: str) -> list:
    """Every child of a client, newest model first.

    v4: reads `job_children`, which is built from the folder tree. Falls
    back to the old jobs.parent_canon query only for a database that
    hasn't been backfilled yet — on live data that query returned rows
    whose parent didn't exist, so the fallback is a bridge, not a source
    of truth. Callers (snapshot umbrella grouping) are unchanged.
    """
    if not parent_canon:
        return []
    kids = children_of(parent_canon)
    if kids:
        return kids
    with _LOCK, _connect() as c:
        rows = c.execute("""
            SELECT * FROM jobs
            WHERE parent_canon=?
            ORDER BY CAST(unit_number AS INTEGER), display_name
        """, (parent_canon,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def find_property_of(canon_key_value: str) -> dict | None:
    """Return the parent property's job row when `canon_key_value` is
    a unit of a known multi-unit property. None when the job has no
    parent, or the parent row doesn't exist in `jobs` yet (siblings
    still group via `parent_canon`, but the umbrella row is optional
    — `find_units_of(parent_canon)` works regardless)."""
    if not canon_key_value:
        return None
    with _LOCK, _connect() as c:
        # v4 first: a job is a child when one of its folders is registered
        # as a child folder. Derived from the folder tree, so unlike the
        # old name-inference it can't invent a parent that doesn't exist.
        row = c.execute("""
            SELECT ch.parent_canon FROM job_children ch
            JOIN job_links l ON l.link_value = ch.folder_path
            WHERE l.canon_key = ? AND l.link_type = ?
            LIMIT 1
        """, (canon_key_value, LINK_FOLDER)).fetchone()
        parent = row["parent_canon"] if row else ""
        if not parent:
            legacy = c.execute(
                "SELECT parent_canon FROM jobs WHERE canon_key=?",
                (canon_key_value,)).fetchone()
            parent = (legacy["parent_canon"] if legacy else "") or ""
        if not parent:
            return None
        prow = c.execute(
            "SELECT * FROM jobs WHERE canon_key=?", (parent,)).fetchone()
    return _row_to_dict(prow)


def group_by_property(canon_keys: Iterable[str]) -> dict[str, list[str]]:
    """Batch grouping for UI rollups. Given a list of canon_keys
    (e.g. every visible audit row), return a dict mapping
    `parent_canon → [child_canon, child_canon, ...]`. Jobs without a
    parent land under their own canon_key as a single-item group so
    the caller can iterate one structure for both grouped + ungrouped
    rows."""
    keys = [k for k in canon_keys if k]
    if not keys:
        return {}
    placeholders = ",".join("?" * len(keys))
    with _LOCK, _connect() as c:
        # v4: parentage comes from the child's FOLDER, via job_children.
        rows = c.execute(f"""
            SELECT l.canon_key AS canon_key, ch.parent_canon AS parent_canon
            FROM job_links l
            JOIN job_children ch ON ch.folder_path = l.link_value
            WHERE l.link_type = ? AND l.canon_key IN ({placeholders})
        """, [LINK_FOLDER, *keys]).fetchall()
        parent_map = {r["canon_key"]: r["parent_canon"] for r in rows}
        # Legacy bridge for a database that hasn't been backfilled.
        missing = [k for k in keys if k not in parent_map]
        if missing:
            ph2 = ",".join("?" * len(missing))
            legacy = c.execute(f"""
                SELECT canon_key, parent_canon FROM jobs
                WHERE canon_key IN ({ph2})
            """, missing).fetchall()
            for r in legacy:
                if r["parent_canon"]:
                    parent_map[r["canon_key"]] = r["parent_canon"]
    out: dict[str, list[str]] = {}
    for k in keys:
        parent = parent_map.get(k) or k
        out.setdefault(parent, []).append(k)
    return out


def get_aliases(canon_key_value: str) -> list[str]:
    """Every alias recorded for a job, in insertion order."""
    if not canon_key_value:
        return []
    with _LOCK, _connect() as c:
        rows = c.execute("""
            SELECT alias FROM job_aliases
            WHERE canon_key=?
            ORDER BY added_at ASC
        """, (canon_key_value,)).fetchall()
    return [r["alias"] for r in rows]


def all_aliases() -> list[dict]:
    """Every (canon_key, alias) pair in ONE query.

    Type-ahead ranks against the whole alias table. Calling get_aliases()
    per job would be 412 round trips — near-free here, but the identical
    code path on the hosted backend is the N+1 that used to cost 36s.
    """
    with _LOCK, _connect() as c:
        rows = c.execute(
            "SELECT canon_key, alias FROM job_aliases").fetchall()
    return [{"canon_key": r["canon_key"], "alias": r["alias"]} for r in rows]


# ── Export / Import ─────────────────────────────────────────────────────

def export_db(path: str, *, include_folders: bool = True) -> dict:
    """Dump shareable state to a JSON file.

    Returns a summary {"jobs": N, "links": M, "aliases": K}.

    What gets included:
      - jobs (full row)
      - aliases (all)
      - links of type 'trello_card' (universal)
      - job folder links (if include_folders=True). Each one also carries
        its `department` + `relative` path so the importer can rebase it
        onto their own root — necessary because OC's root is a synced
        SharePoint library whose local path is per-user. Pass False to
        omit folders entirely.

    What's NOT exported:
      - job_events (per-machine audit log — not useful elsewhere)
      - any link_type not in the allow-list above (machine-specific
        SharePoint / Workcenter caches that won't translate)
    """
    allowed_link_types = {LINK_TRELLO}
    if include_folders:
        # LINK_FOLDER is the type every tool actually writes. "od_folder"
        # was this module's original name for it and never got exported
        # under the real one, so include_folders silently shipped zero
        # folders; keep the legacy spelling readable for any database
        # written before the rename.
        allowed_link_types.update({LINK_FOLDER, "od_folder"})

    out: dict = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now_iso(),
        "exported_by": os.environ.get("USERNAME", ""),
        "jobs": [],
    }
    with _LOCK, _connect() as c:
        jobs = c.execute("SELECT * FROM jobs ORDER BY canon_key ASC").fetchall()
        for j in jobs:
            jd = _row_to_dict(j)
            jd["aliases"] = [
                r["alias"] for r in c.execute("""
                    SELECT alias FROM job_aliases
                    WHERE canon_key=? ORDER BY added_at ASC
                """, (j["canon_key"],)).fetchall()
            ]
            link_rows = c.execute("""
                SELECT * FROM job_links WHERE canon_key=?
                ORDER BY link_type ASC, added_at ASC
            """, (j["canon_key"],)).fetchall()
            links = []
            for r in link_rows:
                if r["link_type"] not in allowed_link_types:
                    continue
                item = {"type": r["link_type"], "value": r["link_value"]}
                # Folder roots differ per machine (a synced SharePoint
                # library's local path contains the syncing user's own
                # profile), so travel with a department + relative path the
                # importer can rebase. `value` stays for older importers.
                if r["link_type"] in (LINK_FOLDER, "od_folder"):
                    dept, rel = split_department_path(r["link_value"])
                    if dept is not None:
                        item["department"] = dept
                        item["relative"] = rel
                links.append(item)
            jd["links"] = links
            out["jobs"].append(jd)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    return {
        "jobs": len(out["jobs"]),
        "links": sum(len(j["links"]) for j in out["jobs"]),
        "aliases": sum(len(j["aliases"]) for j in out["jobs"]),
    }


def import_db(path: str, *, mode: str = "upsert") -> dict:
    """Load a JSON snapshot written by `export_db`.

    mode='upsert' (default): merge into the local DB. Existing jobs
        are updated via the usual partial-update rule; new jobs are
        inserted. Local-only jobs are preserved.
    mode='replace': wipe `jobs` + dependents, then load fresh from
        the file. Use for a clean machine bootstrap.

    Returns {"jobs_added": N, "jobs_updated": M, "links": K,
             "aliases": L}.
    """
    if mode not in ("upsert", "replace"):
        raise ValueError(f"unknown mode: {mode!r}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if mode == "replace":
        with _LOCK, _connect() as c:
            # Cascade deletes from jobs nuke aliases + links + events.
            c.execute("DELETE FROM jobs")
            c.commit()

    added = updated = links_count = aliases_count = rebased_folders = 0
    with _LOCK, _connect() as c:
        for j in data.get("jobs", []):
            key = j.get("canon_key") or canon_key(j.get("display_name", ""))
            if not key:
                continue
            existing = c.execute(
                "SELECT 1 FROM jobs WHERE canon_key=?", (key,)).fetchone()
            if existing is None:
                added += 1
            else:
                updated += 1
            # Use the public upsert path so the partial-update rule
            # applies consistently across import + sync_from_trello.
            upsert_job(
                display_name=j.get("display_name", ""),
                claim_number=j.get("claim_number") or "",
                carrier=j.get("carrier") or "",
                loss_type=j.get("loss_type") or "",
                year=j.get("year"),
                status=j.get("status") or "",
                date_received=j.get("date_received") or "",
                department=j.get("department") or "",
                metadata=j.get("metadata") or None,
            )
            for alias in (j.get("aliases") or []):
                add_alias(key, alias, source="import")
                aliases_count += 1
            for link in (j.get("links") or []):
                lt = link.get("type") or ""
                lv = link.get("value") or ""
                # Rebase a portable folder link onto THIS machine's root
                # for that department. Falls back to the exporter's
                # absolute path when the department isn't configured here
                # (or the export predates the portable form) — no worse
                # than before, and a later config fix + re-import repairs it.
                if link.get("department"):
                    rebased = rebase_department_path(link["department"],
                                                     link.get("relative") or "")
                    if rebased:
                        lv = rebased
                        rebased_folders += 1
                if lt and lv:
                    set_link(key, lt, lv, added_by="import")
                    links_count += 1

    return {
        "jobs_added": added,
        "jobs_updated": updated,
        "links": links_count,
        "aliases": aliases_count,
        "folders_rebased": rebased_folders,
    }


# ── Trello sync ─────────────────────────────────────────────────────────

def sync_from_trello(*, exclude_quality: bool = True,
                       exclude_logs: bool = True,
                       lane_filter: Iterable[str] | None = None,
                       progress_cb=None) -> dict:
    """Refresh the DB from Trello. For every open card on every
    in-scope board: upsert a job, link `trello_card`, record aliases
    for the card name and any "Last, First" comma-swap variant.

    `exclude_quality`: skip AR / billing-dispute boards.
    `exclude_logs`: skip the LOGS - EMS board (closed jobs). Default
    True since the canonical use of this DB is "what's open"; pass
    False to also pull closed jobs (e.g. for historical reporting).

    `lane_filter` (optional) restricts to specific list/lane names —
    useful for cheap targeted refreshes (e.g. only the Initial
    Inspections lane).

    `progress_cb(done, total, current_card_name)` is called per board
    if supplied, for long-running syncs.

    Cards on closed boards still get upserted, but with `status='closed'`
    so the open-jobs view can filter them out without a second pass.

    Returns {"boards": B, "cards": C, "jobs_upserted": J,
             "links_added": L}.
    """
    import trello_client as tc
    boards = tc.list_boards(exclude_quality=exclude_quality)
    # Resolve closed-board IDs once so the per-board loop can stamp
    # status='closed' on those cards without a second Trello call.
    closed_board_ids: set[str] = set()
    try:
        if exclude_logs:
            logs_bid = tc.get_logs_board_id()
            if logs_bid:
                closed_board_ids.add(logs_bid)
                # Drop closed boards from the iteration too — saves the
                # /cards round-trip when the caller doesn't want them.
                boards = [b for b in boards
                          if b.get("id") not in closed_board_ids]
    except Exception:
        pass
    b_total = len(boards)
    cards_total = 0
    jobs_upserted = 0
    links_added = 0

    for bi, b in enumerate(boards, start=1):
        bid = b.get("id")
        if not bid:
            continue
        try:
            lists = tc._call(f"/boards/{bid}/lists",
                              params={"fields": "id,name"}) or []
        except Exception:
            lists = []
        list_name_by_id = {l["id"]: l.get("name", "")
                            for l in lists if l.get("id")}
        try:
            cards = tc._call(f"/boards/{bid}/cards",
                              params={"fields":
                                  "id,name,shortUrl,idList,closed,desc"}) or []
        except Exception:
            cards = []

        for ci, card in enumerate(cards, start=1):
            if card.get("closed"):
                continue
            lane = list_name_by_id.get(card.get("idList", ""), "")
            if lane_filter is not None and lane not in lane_filter:
                continue
            name = (card.get("name") or "").strip()
            if not name:
                continue
            # Strip a trailing " - Carrier" / date suffix from the
            # display_name when building the canon_key (persistence
            # canon already does this). Stash both forms as aliases
            # so a search on the full card title still hits.
            key = canon_key(name)
            if not key:
                continue
            # Trello-source fields: best-effort claim# extraction from
            # the desc, since `desc` parsing is cheap here.
            claim = ""
            carrier = ""
            try:
                fields = tc.parse_card_desc(card.get("desc") or "")
                ins = fields.get("INSURANCE INFORMATION") or {}
                claim = (ins.get("CLAIM NUMBER") or "").strip()
                carrier = (ins.get("INSURANCE COMPANY") or "").strip()
            except Exception:
                pass

            upsert_job(
                display_name=name,
                claim_number=claim,
                carrier=carrier,
                status=("closed" if bid in closed_board_ids else "active"),
                metadata={"board": b.get("name", ""), "lane": lane},
            )
            jobs_upserted += 1
            add_alias(key, name, source="trello")
            set_link(key, "trello_card", card["id"],
                     metadata={"board": b.get("name", ""), "lane": lane},
                     added_by="sync_from_trello")
            links_added += 1
            cards_total += 1
            if progress_cb is not None:
                try:
                    progress_cb(ci, len(cards), name)
                except Exception:
                    pass

    return {
        "boards": b_total,
        "cards": cards_total,
        "jobs_upserted": jobs_upserted,
        "links_added": links_added,
    }


# ── Lifecycle / Pipeline ────────────────────────────────────────────────────
# Per-card stage tracker, populated by pipeline_stages.sync_workspace().
# Stage = position in the EMS job lifecycle (New → ... → Paid). Each upsert
# diffs the prior current_stage; when it changes, stage_entered_at bumps so
# "days in stage" stays honest. We also stamp billed_at on entry to AR and
# paid_at on entry to Paid so cycle-time queries don't need to walk events.


def lifecycle_upsert(entry):
    """Insert or update a job_lifecycle row.

    `entry` is a dict with at least:
        card_id, client_canon, client_display, board_id, board_name,
        list_id, list_name, current_stage, created_at, last_activity_at,
        card_url, owner

    Computed transitions:
      - stage_entered_at: now (UTC) on first insert OR when current_stage
        differs from the prior stored stage; otherwise preserved.
      - billed_at: stamped on entry to 'ar' if not already set.
      - paid_at: stamped on entry to 'paid' if not already set.
    """
    cid = entry.get("card_id")
    if not cid:
        return
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat()
    new_stage = entry.get("current_stage") or ""
    with _LOCK, _connect() as c:
        prior = c.execute(
            "SELECT current_stage, stage_entered_at, billed_at, paid_at "
            "FROM job_lifecycle WHERE card_id = ?", (cid,)).fetchone()
        transition_to_log = None  # populated when stage changes
        if prior is None:
            # First time we've seen this card. The card may already have
            # been sitting in its current lane for weeks — we don't
            # actually know when it landed there without fetching the
            # card-action log. Use the BEST proxy the caller has handed
            # us: dateLastActivity is always ≤ now, and gives a sane
            # lower-bound estimate of "this card was here at least this
            # long". Without this, every Pipeline panel row read 0d in
            # stage right after the first sync, which made stalls
            # invisible. Fall back to now when last_activity is empty
            # or unparseable.
            last_iso = entry.get("last_activity_at") or ""
            stage_entered_at = now_iso
            if last_iso:
                try:
                    dt_la = datetime.fromisoformat(
                        last_iso.split("+")[0].rstrip("Z"))
                    if dt_la < datetime.utcnow():
                        stage_entered_at = dt_la.replace(
                            microsecond=0).isoformat()
                except (ValueError, AttributeError):
                    pass
            billed_at = now_iso if new_stage == "ar" else None
            paid_at   = now_iso if new_stage == "paid" else None
        else:
            prior_stage, prior_entered, prior_billed, prior_paid = prior
            prior_stage = prior_stage or ""
            if new_stage and new_stage != prior_stage:
                stage_entered_at = now_iso
                # Record the transition with days the card spent in the
                # FROM stage. Skip when prior_stage is empty (i.e. row
                # was just inserted) — that's not a real transition.
                if prior_stage:
                    days_from = 0
                    if prior_entered:
                        try:
                            dt_from = datetime.fromisoformat(
                                prior_entered.split("+")[0].rstrip("Z"))
                            days_from = max(
                                0,
                                (datetime.utcnow() - dt_from).days)
                        except (ValueError, AttributeError):
                            pass
                    transition_to_log = (
                        cid, entry.get("client_canon", ""),
                        prior_stage, new_stage, now_iso, days_from)
            else:
                stage_entered_at = prior_entered or now_iso
            billed_at = prior_billed or (
                now_iso if new_stage == "ar" else None)
            paid_at = prior_paid or (
                now_iso if new_stage == "paid" else None)
        c.execute("""
            INSERT INTO job_lifecycle (
                card_id, client_canon, client_display,
                board_id, board_name, list_id, list_name,
                current_stage, stage_entered_at,
                created_at, last_activity_at,
                billed_at, paid_at, card_url, owner, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_id) DO UPDATE SET
                client_canon     = excluded.client_canon,
                client_display   = excluded.client_display,
                board_id         = excluded.board_id,
                board_name       = excluded.board_name,
                list_id          = excluded.list_id,
                list_name        = excluded.list_name,
                current_stage    = excluded.current_stage,
                stage_entered_at = excluded.stage_entered_at,
                created_at       = COALESCE(job_lifecycle.created_at,
                                             excluded.created_at),
                last_activity_at = excluded.last_activity_at,
                billed_at        = COALESCE(job_lifecycle.billed_at,
                                             excluded.billed_at),
                paid_at          = COALESCE(job_lifecycle.paid_at,
                                             excluded.paid_at),
                card_url         = excluded.card_url,
                owner            = excluded.owner,
                updated_at       = excluded.updated_at
        """, (
            cid,
            entry.get("client_canon", ""),
            entry.get("client_display", ""),
            entry.get("board_id", ""),
            entry.get("board_name", ""),
            entry.get("list_id", ""),
            entry.get("list_name", ""),
            new_stage,
            stage_entered_at,
            entry.get("created_at"),
            entry.get("last_activity_at"),
            billed_at,
            paid_at,
            entry.get("card_url", ""),
            entry.get("owner", ""),
            now_iso,
        ))
        if transition_to_log is not None:
            c.execute("""
                INSERT INTO job_stage_transitions (
                    card_id, client_canon, from_stage, to_stage,
                    transitioned_at, days_in_from_stage
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, transition_to_log)
            # Clear the actions-enrichment flag so the next pass
            # picks up THIS transition's exact Trello timestamp —
            # the upsert just stamped stage_entered_at = now (when we
            # noticed the change), but the move on Trello may have
            # been earlier in the gap between syncs.
            c.execute("""
                UPDATE job_lifecycle SET actions_synced_at = NULL
                WHERE card_id = ?
            """, (cid,))
        c.commit()


def lifecycle_delete(card_id):
    """Remove a lifecycle row (and its transition history). Used by
    pipeline_stages.upsert_card / sync_workspace to evict cards that
    match the skip-pattern (templates / labels / admin placeholders)."""
    if not card_id:
        return
    with _LOCK, _connect() as c:
        c.execute("DELETE FROM job_lifecycle WHERE card_id = ?",
                   (card_id,))
        c.execute("DELETE FROM job_stage_transitions WHERE card_id = ?",
                   (card_id,))
        c.commit()


def lifecycle_purge_where(predicate) -> int:
    """One-shot housekeeping — walks every job_lifecycle row and
    deletes any where ``predicate(row_dict)`` returns truthy. Returns
    the count of rows deleted. Used by pipeline_stages.purge_skipped
    to clean up admin/template cards inserted before the skip filter
    was added."""
    to_delete = []
    with _LOCK, _connect() as c:
        rows = c.execute(
            "SELECT card_id, client_display, board_name, list_name "
            "FROM job_lifecycle").fetchall()
        for r in rows:
            if predicate(dict(r)):
                to_delete.append(r["card_id"])
        for cid in to_delete:
            c.execute(
                "DELETE FROM job_lifecycle WHERE card_id = ?", (cid,))
            c.execute(
                "DELETE FROM job_stage_transitions WHERE card_id = ?",
                (cid,))
        c.commit()
    return len(to_delete)


def lifecycle_needs_action_enrichment(*, limit=None):
    """Return rows where actions_synced_at is NULL — they still carry
    the dateLastActivity proxy as stage_entered_at and would benefit
    from a Trello card-action lookup. Limit caps batch size so the
    enrichment pass can be chunked across UI ticks."""
    sql = ("SELECT card_id, list_id, stage_entered_at, current_stage "
           "FROM job_lifecycle "
           "WHERE actions_synced_at IS NULL OR actions_synced_at = '' "
           "ORDER BY stage_entered_at ASC")
    if limit:
        sql += " LIMIT ?"
        args = (int(limit),)
    else:
        args = ()
    with _LOCK, _connect() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def lifecycle_set_stage_entered(card_id, *, stage_entered_at,
                                  mark_actions_synced=True):
    """Update a row's stage_entered_at (and optionally stamp
    actions_synced_at = now). Called by the Phase 4 enrichment pass
    once it determines the true lane-entry date from card actions."""
    if not card_id or not stage_entered_at:
        return
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat()
    with _LOCK, _connect() as c:
        if mark_actions_synced:
            c.execute("""
                UPDATE job_lifecycle
                SET stage_entered_at = ?, actions_synced_at = ?
                WHERE card_id = ?
            """, (stage_entered_at, now_iso, card_id))
        else:
            c.execute("""
                UPDATE job_lifecycle
                SET stage_entered_at = ?
                WHERE card_id = ?
            """, (stage_entered_at, card_id))
        c.commit()


def lifecycle_mark_actions_synced(card_id):
    """Stamp actions_synced_at without changing stage_entered_at —
    used when the enrichment pass tried but found no usable lane-move
    action (rare: card created in this lane and never moved, or list
    was deleted and recreated). Prevents re-trying on every sync."""
    if not card_id:
        return
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat()
    with _LOCK, _connect() as c:
        c.execute("""
            UPDATE job_lifecycle
            SET actions_synced_at = ?
            WHERE card_id = ?
        """, (now_iso, card_id))
        c.commit()


def backfill_stage_entered_dates() -> int:
    """One-shot heal — for lifecycle rows whose stage_entered_at was
    stamped at the FIRST-SEEN sync moment (so stage_entered_at >
    last_activity_at), reset stage_entered_at to last_activity_at.
    last_activity_at is the best proxy we have for "this card was at
    least here this long ago" without fetching card-action history.

    Safe to re-run: the WHERE clause matches only the broken-pattern
    rows (stage_entered_at > last_activity_at), so correctly-set rows
    are skipped. Returns the count of rows touched."""
    with _LOCK, _connect() as c:
        cur = c.execute("""
            UPDATE job_lifecycle
            SET stage_entered_at = last_activity_at
            WHERE last_activity_at IS NOT NULL
              AND last_activity_at != ''
              AND last_activity_at < stage_entered_at
        """)
        c.commit()
        return cur.rowcount


def list_transitions(*, since_iso=None, from_stage=None,
                       card_id=None, limit=None,
                       order="DESC"):
    """Return job_stage_transitions rows. Filters are AND-ed:
      `since_iso` bounds by transitioned_at,
      `from_stage` scopes to one stage's exits,
      `card_id` scopes to one card's full history.
    `order='ASC'` returns oldest-first (useful for timeline rendering);
    default DESC matches the most-recent-first ordering callers expect."""
    sql = "SELECT * FROM job_stage_transitions WHERE 1=1"
    args: list = []
    if since_iso:
        sql += " AND transitioned_at >= ?"
        args.append(since_iso)
    if from_stage:
        sql += " AND from_stage = ?"
        args.append(from_stage)
    if card_id:
        sql += " AND card_id = ?"
        args.append(card_id)
    direction = "ASC" if str(order).upper() == "ASC" else "DESC"
    sql += f" ORDER BY transitioned_at {direction}"
    if limit:
        sql += " LIMIT ?"
        args.append(int(limit))
    with _LOCK, _connect() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def lifecycle_list(paid_window_days=30):
    """Return every job_lifecycle row that's either non-paid OR paid
    within the last `paid_window_days`. Ordered by stage_entered_at
    ascending (oldest in-stage first, since those are the stallers
    the operator wants to surface)."""
    cutoff = ""
    if paid_window_days is not None:
        cutoff_dt = datetime.utcnow() - timedelta(days=paid_window_days)
        cutoff = cutoff_dt.replace(microsecond=0).isoformat()
    with _LOCK, _connect() as c:
        if cutoff:
            rows = c.execute("""
                SELECT * FROM job_lifecycle
                WHERE current_stage != 'paid'
                   OR (paid_at IS NULL)
                   OR (paid_at >= ?)
                ORDER BY stage_entered_at ASC
            """, (cutoff,)).fetchall()
        else:
            rows = c.execute("""
                SELECT * FROM job_lifecycle
                ORDER BY stage_entered_at ASC
            """).fetchall()
    cols = [d[0] for d in rows[0].keys()] if rows and hasattr(
        rows[0], "keys") else None
    return [dict(r) for r in rows]


def lifecycle_get(card_id):
    if not card_id:
        return None
    with _LOCK, _connect() as c:
        row = c.execute(
            "SELECT * FROM job_lifecycle WHERE card_id = ?",
            (card_id,)).fetchone()
    return dict(row) if row else None


def lifecycle_counts_by_stage(paid_window_days=30):
    """Return {stage_key: count} for the active pipeline. Used by the
    Pipeline panel's filter-chip header."""
    out = {}
    for row in lifecycle_list(paid_window_days=paid_window_days):
        s = row.get("current_stage") or ""
        out[s] = out.get(s, 0) + 1
    return out


# Auto-init on import. Safe + idempotent; subsequent imports are no-ops
# once the file exists.
_init_schema()
