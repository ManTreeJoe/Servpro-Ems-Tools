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
                    od_folder, sp_folder, wc_folder, sheet_row, xa_link.
                    Multiple links per (job, type) supported.
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
from persistence import _canon_pin_key as _canon_pin_key_persistence


# Single canonical DB path — sits alongside persistence.json under
# %APPDATA%\EMS Automation\ so coworkers find both files in the same
# place when they need to back the suite up or migrate machines.
DB_PATH = _paths.data("ems_jobs.db")

SCHEMA_VERSION = 2


# ── Multi-unit job detection ────────────────────────────────────────────
#
# Real multi-unit Trello card names we've seen at this franchise:
#   "Avila Apartments 1413- 05/09/26"
#   "Avila Apartments (527) 2/19/26"
#   "Avila Apartments- Unit 226"
#   "Avila Apartments Unit 1027 - Self Pay 2510-517185WTR"
#
# Each is a separate unit on a shared property. We split into
# (property_name, unit_number) so the DB can group them.
_UNIT_DETECT_PATTERNS = (
    # "Property (Unit 123)" / "Property (#123)" / "Property (123)"
    re.compile(
        r"^(?P<prop>.+?)\s*\(\s*(?:unit\s+|#\s*)?(?P<unit>\d{2,4})\s*\)",
        re.IGNORECASE),
    # "Property Unit 123" or "Property- Unit 123" or "Property -Unit 123"
    re.compile(
        r"^(?P<prop>.+?)\s*[-\s]+unit\s+(?P<unit>\d{2,4})\b",
        re.IGNORECASE),
    # "Property Apt 123"
    re.compile(
        r"^(?P<prop>.+?)\s*[-\s]+(?:apt|apartment|suite|ste)\s+(?P<unit>\d{2,4})\b",
        re.IGNORECASE),
    # "Property #123"
    re.compile(
        r"^(?P<prop>.+?)\s+#\s*(?P<unit>\d{2,4})\b",
        re.IGNORECASE),
    # "Property 1234" — last resort, 3-4 digit unit only to avoid
    # confusing single-family job names that happen to end in a number.
    re.compile(
        r"^(?P<prop>.+?)\s+(?P<unit>\d{3,4})\b"),
)


def detect_property_and_unit(display_name: str) -> tuple[str | None, str | None]:
    """Try to split a job display name into (property, unit).

    Returns (None, None) when the name doesn't look multi-unit. The
    property string preserves the original casing (so `canon_key()`
    can normalize once at the storage layer); the unit is the bare
    digit string.

    Negative guards to avoid false positives on single-family AR-board
    card names:
      • Prop contains a comma → "Last, First" person form, never a
        property name.
      • Unit looks like a YEAR (2000-2099) AND the form was the
        paren-only variant → very likely a "(2025)" job-year tag
        on a person-named card. Real units don't tend to land in
        this exact slot. Hyphen/Unit-prefixed forms ARE allowed to
        match year-shaped numbers because those formats are
        unambiguously multi-unit ("Apt 2025" still means apt 2025).
    """
    s = (display_name or "").strip()
    if not s:
        return None, None
    for pat in _UNIT_DETECT_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        prop = m.group("prop").strip().rstrip("-").rstrip(",").strip()
        unit = m.group("unit").strip()
        if not (prop and unit):
            continue
        if prop.lower() == "unit":
            continue
        if "," in prop:
            # "Hankiewicz, Markus (2024) - State Farm" — person name
            # masquerading as a property. Skip.
            continue
        try:
            unit_int = int(unit)
        except ValueError:
            unit_int = None
        # Only the paren-form and the bare-number-fallback patterns
        # are ambiguous with year tags; reject year-shaped units on
        # those two paths.
        is_paren_or_bare = (pat is _UNIT_DETECT_PATTERNS[0]
                             or pat is _UNIT_DETECT_PATTERNS[-1])
        if (is_paren_or_bare and unit_int is not None
                and 2000 <= unit_int <= 2099):
            continue
        return prop, unit
    return None, None

# Serialize all writes through one lock — SQLite handles read concurrency
# fine but write contention from multiple panels on the same process can
# race. The connection itself is opened per-call so threads each get
# their own (sqlite3 module objects aren't safely shared across threads).
_LOCK = threading.RLock()


# ── Canonicalization ────────────────────────────────────────────────────

def canon_key(name: str) -> str:
    """Return the storage key for `name`. Same rule persistence uses for
    pin keys: casefold + collapse whitespace + strip " - Carrier" suffix.
    Shared so a pin written here lines up with one written by another
    tool that consulted `persistence._canon_pin_key` directly."""
    return _canon_pin_key_persistence(name)


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
                unit_number     TEXT
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

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(
        microsecond=0, tzinfo=None).isoformat()


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


# ── Write API ───────────────────────────────────────────────────────────

def upsert_job(*, display_name: str,
                claim_number: str = "",
                carrier: str = "",
                loss_type: str = "",
                year: int | None = None,
                status: str = "",
                date_received: str = "",
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
    # Auto-detect property + unit from the display name. The parent
    # canon is set unconditionally — even if the umbrella property
    # row doesn't exist yet, siblings still share the same parent_canon
    # so `find_units_of(parent)` rolls them up.
    prop_name, unit_num = detect_property_and_unit(display_name)
    parent_canon_value = canon_key(prop_name) if prop_name else None
    # Guard against self-parenting (the property root has no parent).
    if parent_canon_value == key:
        parent_canon_value = None
    with _LOCK, _connect() as c:
        existing = c.execute(
            "SELECT * FROM jobs WHERE canon_key = ?", (key,)).fetchone()
        if existing is None:
            c.execute("""
                INSERT INTO jobs
                    (canon_key, display_name, claim_number, carrier,
                     loss_type, year, status, date_received,
                     first_seen_at, last_seen_at, metadata_json,
                     parent_canon, unit_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, display_name, claim_number, carrier, loss_type,
                  year, status, date_received, now, now, md_json,
                  parent_canon_value, unit_num))
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
            c.execute("""
                UPDATE jobs SET
                    display_name=?, claim_number=?, carrier=?, loss_type=?,
                    year=?, status=?, date_received=?, last_seen_at=?,
                    metadata_json=?, parent_canon=?, unit_number=?
                WHERE canon_key=?
            """, (new_vals["display_name"], new_vals["claim_number"],
                  new_vals["carrier"], new_vals["loss_type"],
                  new_vals["year"], new_vals["status"],
                  new_vals["date_received"], new_vals["last_seen_at"],
                  new_vals["metadata_json"], new_parent, new_unit, key))
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
        c.commit()


def remove_link(canon_key_value: str, link_type: str,
                link_value: str = "") -> None:
    """Drop a link. Blank `link_value` removes ALL links of the
    given type for the job (handy when nuking a stale type)."""
    if not (canon_key_value and link_type):
        return
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

def find_job_by_name(name: str) -> dict | None:
    """Resolve a job from any spelling we've seen. Tries:
      1. Direct canon_key match on `jobs.canon_key`.
      2. Alias canon match on `job_aliases.alias_canon`.
    Returns the job dict (with `metadata` parsed) or None.
    """
    if not name:
        return None
    key = canon_key(name)
    if not key:
        return None
    with _LOCK, _connect() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE canon_key=?", (key,)).fetchone()
        if row:
            return _row_to_dict(row)
        row = c.execute("""
            SELECT j.* FROM jobs j
            JOIN job_aliases a ON a.canon_key = j.canon_key
            WHERE a.alias_canon = ?
            LIMIT 1
        """, (key,)).fetchone()
        return _row_to_dict(row)


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


def find_units_of(parent_canon: str) -> list[dict]:
    """Every job whose `parent_canon` equals `parent_canon`, sorted by
    unit number when the unit looks numeric, otherwise display_name.
    Empty list when no children exist."""
    if not parent_canon:
        return []
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
        row = c.execute(
            "SELECT parent_canon FROM jobs WHERE canon_key=?",
            (canon_key_value,)).fetchone()
        if not row or not row["parent_canon"]:
            return None
        prow = c.execute(
            "SELECT * FROM jobs WHERE canon_key=?",
            (row["parent_canon"],)).fetchone()
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
        rows = c.execute(f"""
            SELECT canon_key, parent_canon FROM jobs
            WHERE canon_key IN ({placeholders})
        """, keys).fetchall()
    parent_map = {r["canon_key"]: r["parent_canon"] for r in rows}
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


# ── Export / Import ─────────────────────────────────────────────────────

def export_db(path: str, *, include_folders: bool = True) -> dict:
    """Dump shareable state to a JSON file.

    Returns a summary {"jobs": N, "links": M, "aliases": K}.

    What gets included:
      - jobs (full row)
      - aliases (all)
      - links of type 'trello_card' (universal)
      - links of type 'od_folder' (if include_folders=True — assumes
        recipients share the same X:\\ mount; pass False for users on
        a different file server)

    What's NOT exported:
      - job_events (per-machine audit log — not useful elsewhere)
      - any link_type not in the allow-list above (machine-specific
        SharePoint / Workcenter caches that won't translate)
    """
    allowed_link_types = {"trello_card"}
    if include_folders:
        allowed_link_types.add("od_folder")

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
            jd["links"] = [
                {"type": r["link_type"], "value": r["link_value"]}
                for r in link_rows
                if r["link_type"] in allowed_link_types
            ]
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

    added = updated = links_count = aliases_count = 0
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
                metadata=j.get("metadata") or None,
            )
            for alias in (j.get("aliases") or []):
                add_alias(key, alias, source="import")
                aliases_count += 1
            for link in (j.get("links") or []):
                lt = link.get("type") or ""
                lv = link.get("value") or ""
                if lt and lv:
                    set_link(key, lt, lv, added_by="import")
                    links_count += 1

    return {
        "jobs_added": added,
        "jobs_updated": updated,
        "links": links_count,
        "aliases": aliases_count,
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
