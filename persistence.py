"""
Shared persistent state for the Linguar Hub.
Stores resolved checkbox states per audit run, contact emails, folder
overrides, and any other cross-session memory in a single state.json
next to the scripts.

Reads are cached in memory and invalidated by mtime so external writes (a
second instance of the app, manual edits) are still picked up. Without this
cache every UI checkbox click hit disk twice.
"""
import os
import json
import time
import threading
from datetime import datetime, date as _date, timedelta as _timedelta

import paths

_STATE_PATH = paths.data("state.json")

_CACHE_LOCK  = threading.Lock()
_CACHE       = None   # most recent state dict, or None when never loaded
_CACHE_MTIME = None   # mtime when _CACHE was populated; mismatch → reload


def _json_default(obj):
    """Coerce non-JSON-native values to safe shapes for json.dump.

    Why: row producers across the app (ar_followup, weekly_checkins,
    trello_hygiene, estimate_requests, etc.) occasionally pass raw
    datetime / date / set / Decimal objects into row dicts that end up
    stored in state.json. Without a default handler, ANY such leak
    raises `TypeError: Object of type datetime is not JSON serializable`
    from inside _save — which silently aborts the write and leaves the
    on-disk state stale. The user-visible symptom is "the hygiene scan
    ran for 14 minutes and then nothing happened" (the scan succeeded,
    the cache write failed). Handling it here makes the whole
    persistence layer permanently resilient to that class of bug.
    """
    if isinstance(obj, datetime):
        return obj.isoformat(timespec="seconds")
    if isinstance(obj, _date):
        return obj.isoformat()
    if isinstance(obj, _timedelta):
        return obj.total_seconds()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, bytes):
        try: return obj.decode("utf-8", errors="replace")
        except Exception: return ""
    # Fall back to repr — better than crashing the whole save.
    return repr(obj)


def _read_from_disk():
    """Read + schema-sanitize state.json. Returns ({}, mtime) on missing,
    corrupted, or unreadable file (mtime is None when the file is missing)."""
    try:
        current_mtime = os.path.getmtime(_STATE_PATH)
    except OSError:
        current_mtime = None
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, None
    except (OSError, json.JSONDecodeError) as ex:
        # Corrupted or unreadable state.json — log so we have a chance to
        # notice persistence loss instead of silently resetting every key.
        try:
            import ems_log
            ems_log.error("persistence", f"state.json read failed: {ex}")
        except Exception:
            pass
        return {}, current_mtime

    # Schema sanity — auto-repair fields that got corrupted to wrong types
    if not isinstance(data, dict):
        return {}, current_mtime
    if not isinstance(data.get("resolved_issues", {}), dict):
        data["resolved_issues"] = {}
    if not isinstance(data.get("commercial", {}), dict):
        data["commercial"] = {}
    if not isinstance(data.get("folder_paths"), dict):
        data["folder_paths"] = {}
    if not isinstance(data.get("window_geometry", {}), dict):
        data["window_geometry"] = {}
    if not isinstance(data.get("notes", {}), dict):
        data["notes"] = {}
    if not isinstance(data.get("estimator_emails", {}), dict):
        data["estimator_emails"] = {}
    if not isinstance(data.get("escalation_emails", {}), dict):
        data["escalation_emails"] = {}
    if not isinstance(data.get("escalations_sent", {}), dict):
        data["escalations_sent"] = {}
    if not isinstance(data.get("apa_eod_recipients", []), list):
        data["apa_eod_recipients"] = []
    if not isinstance(data.get("paned_sash", {}), dict):
        data["paned_sash"] = {}
    if not isinstance(data.get("apa_franchises", []), list):
        data["apa_franchises"] = []
    if not isinstance(data.get("apa_franchise_tags", {}), dict):
        data["apa_franchise_tags"] = {}
    if not isinstance(data.get("sp_match_rejects", {}), dict):
        data["sp_match_rejects"] = {}
    if not isinstance(data.get("sp_match_overrides", {}), dict):
        data["sp_match_overrides"] = {}
    if not isinstance(data.get("user_techs"), dict):
        data["user_techs"] = {}
    ut = data["user_techs"]
    if not isinstance(ut.get("names"), list):
        ut["names"] = []
    if not isinstance(ut.get("abbrev"), dict):
        ut["abbrev"] = {}
    if not isinstance(data.get("audit_cache"), dict):
        data["audit_cache"] = {}
    if not isinstance(data.get("trello_card_ids"), dict):
        data["trello_card_ids"] = {}
    if not isinstance(data.get("closeout_drafted"), dict):
        data["closeout_drafted"] = {}
    if not isinstance(data.get("ipr_resolved"), dict):
        data["ipr_resolved"] = {}
    if not isinstance(data.get("property_groups"), dict):
        data["property_groups"] = {}
    if not isinstance(data.get("dismissed_card_warnings"), dict):
        data["dismissed_card_warnings"] = {}
    # hygiene_scan_cache is a sidecar file now — deliberately NOT
    # defaulted here, or every load would put the key back in state.json.
    if not isinstance(data.get("estimate_requests"), dict):
        data["estimate_requests"] = {}
    if not isinstance(data.get("estimator_trello_handles"), dict):
        data["estimator_trello_handles"] = {}
    if not isinstance(data.get("weekly_note_sent"), dict):
        data["weekly_note_sent"] = {}
    # Schema migration: v1 stored a single string per client
    # ({"Joe": "abc123"}); v2 stores a list ({"Joe": ["abc123"]}) so a
    # job duplicated across boards can be linked to all of them. Coerce
    # leftover string entries on read so callers never see the old
    # shape after the first load post-upgrade.
    #
    # v3 canonicalizes keys (lowercase, whitespace-collapsed, " - Carrier"
    # suffix stripped) so APA's "Doe, John - State Farm" and the audit's
    # "Doe, John" map to the same entry. Without this, pins set in APA
    # were silently invisible everywhere else.
    raw_pins = data["trello_card_ids"]
    canon_pins: dict[str, list] = {}
    for k, v in list(raw_pins.items()):
        if isinstance(v, str):
            ids = [v] if v else []
        elif isinstance(v, list):
            ids = [x for x in v if x]
        else:
            ids = []
        ck = _canon_pin_key(k)
        if not ck:
            continue
        bucket = canon_pins.setdefault(ck, [])
        for cid in ids:
            if cid not in bucket:
                bucket.append(cid)
    data["trello_card_ids"] = canon_pins

    # Same canonicalization for `folder_paths` — pins set from one surface
    # ("Sanchez, Anthony") were invisible to lookups from another surface
    # ("Sanchez, Anthony - State Farm") because keys weren't normalized.
    # Last-write-wins on collision: if two raw keys collapse to the same
    # canonical key, the one we see last in dict iteration order keeps
    # its path. Acceptable — both pointed at the same logical client.
    raw_paths = data["folder_paths"]
    canon_paths: dict[str, str] = {}
    for k, v in list(raw_paths.items()):
        if not isinstance(v, str) or not v:
            continue
        ck = _canon_pin_key(k)
        if not ck:
            continue
        canon_paths[ck] = v
    data["folder_paths"] = canon_paths

    return data, current_mtime


def _canon_pin_key(client) -> str:
    """Canonicalize a client name for the pin store. Stable across:
      • case ('Doe, John' == 'doe, john'),
      • whitespace ('Doe, John ' == 'Doe,  John'),
      • comma-space drift ('Doe,John' == 'Doe, John'),
      • trailing " - Carrier" / "- Carrier" / " -Carrier" suffix
        added by APA (`_strip_to_base` form, plus the no-space
        variants that surface when users type carrier inline).
    The carrier suffix is informational metadata, not part of the
    job's identity — two pin writes from different surfaces should
    land on the same key. Returns '' for falsy/blank input.

    Reason the variants matter: the APA Monitor row "📌 unpinned"
    bug came from a pin set on the audit side as 'doe, john' but
    the APA looked up 'doe,john - aaa' (no space after comma + no
    space around the carrier hyphen). The pin existed; the strict
    canon-key wasn't finding it.

    ── Sibling canon functions (don't confuse) ──────────────────────
    `ems_db.canon_key` → thin alias to this one (shares storage key).
    `snapshots_excel._canon_name_key` → preserves " - X" suffix because
        on the Snapshots workbook " - X" is usually a sub-job identifier
        (commercial unit / tenant) that MUST stay distinct.
    `initial_upload_queue._norm_client_for_run_doc` → does comma-swap
        ("Last, First" → "first last") for fuzzy run-doc text matching;
        no carrier stripping.
    Use THIS function when: pinning a Trello card to a client, looking
    up a saved folder path, matching an APA row to an audit row.
    """
    import re as _re
    s = (client or "").strip()
    if not s:
        return ""
    # Drop everything from the FIRST " - " onward. APA's
    # `_strip_to_base` gives "Last, First - Carrier"; bare-name
    # surfaces (audit, snapshot, job notes) don't include " - ".
    # Real client names with an embedded hyphen use "-" without
    # spaces (e.g. "Smith-Jones"), so splitting on " - " is safe.
    head = s.split(" - ", 1)[0].strip()
    # Also strip the no-space-after variant " -Carrier" (e.g.
    # "Smith, John -AAA") — fragment must be a short uppercase
    # alpha to avoid eating "Smith-Jones".
    head = _re.sub(r"\s+-\s*[A-Z][A-Za-z0-9&/]{0,15}\s*$", "", head)
    # And the no-space-before variant "- Carrier" (e.g.
    # "Smith, John- AAA"). Same guard — short alpha tail only.
    head = _re.sub(r"-\s+[A-Z][A-Za-z0-9&/]{0,15}\s*$", "", head)
    # Both rules above only match a SINGLE-word tail, so the no-space
    # variants missed every multi-word carrier — and most carriers are
    # two words. "Smith, John - State Farm" and "Smith, John- State Farm"
    # canon'd to different keys, i.e. two jobs for one insured; on the
    # live index 8 rows were sitting on a "- Self Pay" / "- State Farm"
    # key that the spaced spelling would never find.
    #
    # Widen it ONLY for a tail we actually recognise as a carrier. The
    # dash is not reserved for carriers — it also separates units, dates,
    # sub-properties and claim numbers ("Avila Apartments- Unit 226",
    # "Keystone- Highland Village- (Unit 168)", "7 -11  (Norco)",
    # "MUSD Oak Meadows Elementary- 2511-565898WTR"). A blanket split was
    # measured against the live index first and folded every unit of a
    # complex, and every school in a district, onto one key. `is_known`
    # exists for this exact call — see its docstring.
    m = _re.search(r"(?:\s+-\s*|-\s+)([^-]+?)\s*$", head)
    if m:
        try:
            import carriers as _carriers
            if _carriers.is_known(m.group(1)):
                head = head[:m.start()]
        except Exception:
            pass
    head = head.strip()
    # Normalize comma-space: ensure each comma has exactly one
    # space after it. Catches "Doe,John" → "Doe, John".
    head = _re.sub(r",\s*", ", ", head)
    # Collapse any remaining internal whitespace runs.
    head = " ".join(head.split())
    return head.casefold()


def _load():
    """Return the current state dict, served from cache when state.json's
    mtime hasn't changed since last read. Callers may mutate the returned
    dict and pass it to _save() — we deliberately do NOT deepcopy because
    the existing accessor pattern is `state = _load(); mutate; _save(state)`
    where mutating the cached dict directly is fine and saves a clone."""
    global _CACHE, _CACHE_MTIME
    with _CACHE_LOCK:
        try:
            disk_mtime = os.path.getmtime(_STATE_PATH)
        except OSError:
            disk_mtime = None
        if _CACHE is not None and disk_mtime == _CACHE_MTIME:
            return _CACHE
        data, mtime = _read_from_disk()
        _CACHE = data
        _CACHE_MTIME = mtime
        return data


def _save(state):
    """Atomic write via temp + rename. Updates the in-memory cache so the
    next _load() doesn't have to re-read what we just wrote.

    Concurrency: serialized under `_CACHE_LOCK`. Multiple writer threads
    (Hygiene scan, APA sync, IUQ refresh, dispute scan, etc.) all hit
    `_save` independently — without the lock around the dump+rename
    pair, two threads racing to the same `.tmp` filename could
    corrupt the JSON before the rename. Holding the lock for the
    full I/O sequence keeps writes ordered."""
    global _CACHE, _CACHE_MTIME
    # Unique tmp suffix as a belt-and-braces guard in case some future
    # caller bypasses the lock — corrupt-tmp is a hard-to-debug class
    # of bug, and the cost is one rand() per save.
    import uuid as _uuid
    import copy as _copy
    tmp = _STATE_PATH + f".tmp-{_uuid.uuid4().hex[:8]}"
    with _CACHE_LOCK:
        try:
            # Dump a STABLE snapshot, not the live cache. _load() hands
            # callers the shared _CACHE dict and they mutate it without the
            # lock, so json.dump iterating _CACHE directly could hit
            # "dictionary changed size during iteration" (an uncaught
            # RuntimeError that killed the writer thread and lost the save).
            # deepcopy under the lock is fast; retry the rare case where a
            # concurrent mutation lands mid-copy.
            snapshot = state
            for _attempt in range(3):
                try:
                    snapshot = _copy.deepcopy(state)
                    break
                except RuntimeError:
                    continue
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=_json_default)
            os.replace(tmp, _STATE_PATH)
            _CACHE = state
            try:
                _CACHE_MTIME = os.path.getmtime(_STATE_PATH)
            except OSError:
                _CACHE_MTIME = None
        except OSError as ex:
            try:
                import ems_log
                ems_log.error("persistence",
                              f"state.json write failed: {ex}")
            except Exception:
                pass
            # Best-effort cleanup of the abandoned tmp; ignore failures.
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass


# ── Sidecar caches ─────────────────────────────────────────────────────────
#
# Three keys were 85% of state.json (5.6 MB of 6.6): xa_email_bodies
# (3.1 MB of cached Graph message bodies), hygiene_scan_cache (~1 MB of
# the last scan's rows) and dispute_email_seen (a 5,000-id dedupe list).
#
# That mattered far beyond disk space. `_save()` deepcopies the whole
# state and re-encodes it with indent=2 on EVERY mutation anywhere in the
# app — ticking one checkbox rewrote 5.9 MB. A single 13-job audit spent
# ~3.4s of pure CPU on 8 of those writes, before any network work.
#
# All three are regenerable caches, so they get their own files and a
# normal save touches ~800 KB. Each sidecar is written only when its own
# value changes, so the audit's state writes no longer touch them at all.
_SIDECAR_FILES = {
    "xa_email_bodies":    "cache_xa_email_bodies.json",
    "hygiene_scan_cache": "cache_hygiene_scan.json",
    "dispute_email_seen": "cache_dispute_email_seen.json",
}
_SIDECAR_LOCK = threading.Lock()
_SIDECAR_CACHE = {}    # key -> (value, mtime_when_read)


def _sidecar_path(key):
    return paths.data(_SIDECAR_FILES[key])


def _sidecar_load(key, default=None):
    """Read one sidecar, mtime-cached like the main state.

    Migration: a key still living in state.json is adopted on first read.
    The sidecar is written BEFORE the key is dropped from state, so a
    failure anywhere leaves the original value exactly where it was.
    """
    path = _sidecar_path(key)
    with _SIDECAR_LOCK:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        hit = _SIDECAR_CACHE.get(key)
        if hit is not None and hit[1] == mtime and mtime is not None:
            return hit[0]
        if mtime is not None:
            try:
                with open(path, encoding="utf-8") as f:
                    val = json.load(f)
                _SIDECAR_CACHE[key] = (val, mtime)
                return val
            except (OSError, ValueError):
                pass    # unreadable/corrupt cache → fall through, rebuild
    # No sidecar yet. Adopt the value out of state.json if it's there.
    state = _load()
    if key in state:
        legacy = state[key]
        if legacy not in (None, {}, []):
            _sidecar_save(key, legacy)
            with _CACHE_LOCK:
                fresh = _CACHE if _CACHE is not None else state
            fresh.pop(key, None)
            _save(fresh)
            return legacy
        state.pop(key, None)
    return default


def _sidecar_save(key, value):
    """Atomic write of one sidecar. Never raises — these are caches, and
    losing one costs a re-fetch, not data."""
    import uuid as _uuid
    path = _sidecar_path(key)
    tmp = path + f".tmp-{_uuid.uuid4().hex[:8]}"
    with _SIDECAR_LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(value, f, default=_json_default)
            os.replace(tmp, path)
            try:
                _SIDECAR_CACHE[key] = (value, os.path.getmtime(path))
            except OSError:
                _SIDECAR_CACHE.pop(key, None)
        except (OSError, ValueError, TypeError) as ex:
            try:
                import ems_log
                ems_log.error("persistence", f"{key} cache write failed: {ex}")
            except Exception:
                pass
            try:
                os.remove(tmp)
            except OSError:
                pass


def get(key, default=None):
    if key in _SIDECAR_FILES:
        val = _sidecar_load(key, default)
        return default if val is None else val
    return _load().get(key, default)


def set_value(key, value):
    if key in _SIDECAR_FILES:
        _sidecar_save(key, value)
        return
    state = _load()
    state[key] = value
    _save(state)


# ── Trello checklist-progress cache (X/Y chip across panels) ───────────────
#
# Populated by IUQ + Hygiene full scans that already fetch checklists.
# Read by the audit row to render a "✓ X/Y" chip without re-fetching.
# Bounded to ~500 entries (LRU-trim oldest by fetched_at on insert) so a
# year of card churn doesn't bloat state.json.

_CHECKLIST_CACHE_CAP = 500


def set_checklist_progress(card_id, done, total):
    if not card_id:
        return
    state = _load()
    cache = state.setdefault("trello_checklist_progress", {})
    if not isinstance(cache, dict):
        cache = {}
        state["trello_checklist_progress"] = cache
    cache[card_id] = {
        "done": int(done or 0),
        "total": int(total or 0),
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    # Trim oldest if past cap. Cheap O(N) — N is small (≤500).
    if len(cache) > _CHECKLIST_CACHE_CAP:
        keep = sorted(cache.items(),
                       key=lambda kv: (kv[1] or {}).get("fetched_at", ""),
                       reverse=True)[:_CHECKLIST_CACHE_CAP]
        state["trello_checklist_progress"] = dict(keep)
    _save(state)


def set_checklist_progress_bulk(updates):
    """Same as `set_checklist_progress` but writes a batch in one disk
    flush. `updates` is an iterable of (card_id, done, total) tuples."""
    if not updates:
        return
    state = _load()
    cache = state.setdefault("trello_checklist_progress", {})
    if not isinstance(cache, dict):
        cache = {}
        state["trello_checklist_progress"] = cache
    now = datetime.utcnow().isoformat(timespec="seconds")
    for card_id, done, total in updates:
        if not card_id:
            continue
        cache[card_id] = {
            "done": int(done or 0),
            "total": int(total or 0),
            "fetched_at": now,
        }
    if len(cache) > _CHECKLIST_CACHE_CAP:
        keep = sorted(cache.items(),
                       key=lambda kv: (kv[1] or {}).get("fetched_at", ""),
                       reverse=True)[:_CHECKLIST_CACHE_CAP]
        state["trello_checklist_progress"] = dict(keep)
    _save(state)


def get_checklist_progress(card_id):
    """Return the cached `{done, total, fetched_at}` entry for `card_id`,
    or None when no cache entry exists. Caller decides whether the
    age is acceptable for the surface they're rendering into."""
    if not card_id:
        return None
    cache = _load().get("trello_checklist_progress") or {}
    if not isinstance(cache, dict):
        return None
    entry = cache.get(card_id)
    return entry if isinstance(entry, dict) else None


# ── Resolved audit issues (per run_date + client + issue text) ───────────────

# `::` is the field separator across audit/cache keys; if any part
# contains a literal `::`, downstream `key.split("::", 1)` /
# `key.endswith(suffix)` lookups in the same module will get confused
# (date_part can shift, suffix matches can collide). No production data
# has ever included `::`, so escaping inside parts to `:_:` is a no-op
# for existing state but immunizes future issue text from breakage.
def _esc(part):
    return str(part).replace("::", ":_:")


def _audit_key(run_date, client, issue):
    return f"{_esc(run_date)}::{_esc(client)}::{_esc(issue)}"


def is_resolved(run_date, client, issue):
    resolved = _load().get("resolved_issues", {})
    return resolved.get(_audit_key(run_date, client, issue), False)


def set_resolved(run_date, client, issue, done):
    state = _load()
    resolved = state.setdefault("resolved_issues", {})
    key = _audit_key(run_date, client, issue)
    if done:
        resolved[key] = True
    else:
        resolved.pop(key, None)
    _save(state)


def last_resolved_within(client, issue, days=7):
    """Return the most recent run_date (MM-DD-YYYY string) on which the
    user marked this client+issue resolved, within the last `days` days.
    None if there's no such record.

    Used by the audit's carry-forward UI: when an item was marked done
    on a recent prior audit but the underlying form/photo is still
    missing today, the checkbox surfaces with the prior date as a
    reminder so the user only has to re-confirm if something changed.
    """
    resolved = _load().get("resolved_issues", {})
    if not resolved:
        return None
    cutoff = time.time() - days * 86400
    suffix = f"::{_esc(client)}::{_esc(issue)}"
    best = None
    best_ts = -1
    for key, val in resolved.items():
        if not val:
            continue
        if not key.endswith(suffix):
            continue
        date_part = key.split("::", 1)[0]
        try:
            ts = datetime.strptime(date_part, "%m-%d-%Y").timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        if ts > best_ts:
            best_ts = ts
            best = date_part
    return best


def clear_resolved_history(client, issue, days=7):
    """Remove ALL resolved-issues entries for a specific client+issue
    across recent run_dates.  Called when the commercial toggle is
    explicitly unchecked so carry-forward doesn't re-pre-check items
    the user deliberately unmarked."""
    state = _load()
    resolved = state.get("resolved_issues", {})
    if not resolved:
        return
    cutoff = time.time() - days * 86400
    suffix = f"::{_esc(client)}::{_esc(issue)}"
    to_remove = []
    for k in list(resolved):
        if not k.endswith(suffix):
            continue
        date_part = k.split("::", 1)[0]
        try:
            ts = datetime.strptime(date_part, "%m-%d-%Y").timestamp()
        except Exception:
            ts = None
        # Remove if within the carry-forward window (or date unreadable).
        if ts is None or ts >= cutoff:
            to_remove.append(k)
    for k in to_remove:
        resolved.pop(k, None)
    if to_remove:
        _save(state)


# ── Per-day unit pin (Run Audit) ─────────────────────────────────────────────
#
# Multi-unit / multi-property jobs sometimes show up on the daily run-doc
# without a unit number (e.g. "Avila Apartments" with no "1416"). The
# audit's auto-resolver picks the first matching year-folder, which can
# be the wrong one. The per-day unit pin lets the user tell the audit
# "for TODAY, this row points at THIS specific folder" without making it
# a permanent pin (tomorrow's "Avila Apartments" might be a different
# unit). Cleared whenever the user clicks Reset; otherwise persists so
# re-running the audit on the same run-doc keeps the user's pick.
#
# Schema: state["run_day_units"][run_date_mmddyyyy][_canon_pin_key(client)] = absolute_path

def _run_day_units_for(run_date):
    if not run_date:
        return {}
    data = _load().get("run_day_units") or {}
    return data.get(str(run_date)) or {}


def get_run_day_units(run_date, client):
    """Return the list of day-pinned folder paths for this (run_date,
    client). Always a list — empty when not pinned, length 1 for the
    common single-unit case, length ≥ 2 when the user picked multiple
    unit subfolders from a multi-unit umbrella property.

    Reads the legacy single-string format transparently: pre-multi-pin
    writes stored a bare string; we promote those to `[string]` on
    read so callers never see the old shape."""
    key = _canon_pin_key(client)
    if not key or not run_date:
        return []
    raw = _run_day_units_for(run_date).get(key)
    if not raw:
        return []
    if isinstance(raw, list):
        return [p for p in raw if p]
    # Legacy single-string entry
    return [raw]


def get_run_day_unit(run_date, client):
    """Return the FIRST day-pinned folder path for this (run_date,
    client), or "" if none. Compatibility shim around
    `get_run_day_units` — use the multi version when the caller needs
    every pinned unit (audit row replication)."""
    paths = get_run_day_units(run_date, client)
    return paths[0] if paths else ""


def set_run_day_units(run_date, client, paths):
    """Pin `client` to a list of paths for `run_date` only. Pass an
    empty list / None to clear. Dedupes while preserving caller order
    so the first pinned unit remains the 'primary' for single-unit
    lookups."""
    key = _canon_pin_key(client)
    if not key or not run_date:
        return
    data = _load()
    bucket = data.setdefault("run_day_units", {}).setdefault(
        str(run_date), {})
    cleaned = [p for p in (paths or []) if p]
    if not cleaned:
        bucket.pop(key, None)
    else:
        seen = set()
        deduped = []
        for p in cleaned:
            if p not in seen:
                seen.add(p)
                deduped.append(p)
        bucket[key] = deduped
    _save(data)


def set_run_day_unit(run_date, client, path):
    """Single-path convenience. Replaces ANY existing pin list for
    this (run_date, client). Use `set_run_day_units` directly to add
    to a list without dropping the others."""
    set_run_day_units(run_date, client, [path] if path else [])


def list_run_day_units(run_date):
    """Return `{canon_client_key: [paths]}` for `run_date`. Used by
    the audit's lookup composer + diagnostics. Always lists — legacy
    string entries are promoted on read."""
    out = {}
    for k, v in _run_day_units_for(run_date).items():
        if isinstance(v, list):
            out[k] = [p for p in v if p]
        elif v:
            out[k] = [v]
    return out


# ── SP Recent dismissals ─────────────────────────────────────────────────────
#
# Lets the user hide an SP Recent row whose folder maps to the wrong thing
# (or that they otherwise don't want surfaced). Stored as a dict keyed by
# the SP folder path so the same SP folder can be dismissed independently
# of any client mapping. Persists indefinitely — the user can clear all
# dismissals via the "Show dismissed" toggle's reset action.
#
# Schema: state["sp_recent_dismissed"] = {sp_path: "YYYY-MM-DD"}

def _sp_dismiss_key(sp_path):
    return (sp_path or "").strip().lower()


def is_sp_recent_dismissed(sp_path):
    if not sp_path:
        return False
    return _sp_dismiss_key(sp_path) in (
        _load().get("sp_recent_dismissed", {}) or {})


def dismiss_sp_recent(sp_path):
    """Hide this SP folder from SP Recent results going forward. The
    dismissal persists until the user clicks 'Show dismissed → Clear'."""
    key = _sp_dismiss_key(sp_path)
    if not key:
        return
    data = _load()
    data.setdefault("sp_recent_dismissed", {})[key] = \
        datetime.today().strftime("%Y-%m-%d")
    _save(data)


def undismiss_sp_recent(sp_path):
    """Restore a single dismissed SP folder to the visible list."""
    key = _sp_dismiss_key(sp_path)
    if not key:
        return
    data = _load()
    rec = data.get("sp_recent_dismissed", {})
    if key in rec:
        rec.pop(key, None)
        _save(data)


def list_sp_recent_dismissals():
    """Return [(sp_path, dismissed_yyyy_mm_dd), ...] sorted newest-first.
    Used by the 'Show dismissed' panel so the user can review + restore."""
    rec = _load().get("sp_recent_dismissed", {}) or {}
    return sorted(rec.items(), key=lambda kv: kv[1], reverse=True)


def clear_sp_recent_dismissals():
    data = _load()
    if "sp_recent_dismissed" in data:
        data["sp_recent_dismissed"] = {}
        _save(data)


# ── IUQ (Initial Upload Queue) dismissals ────────────────────────────────────
#
# Lets the user remove an auto-pulled (Trello-card) IUQ row that shouldn't be
# in the queue. Keyed by card_id so it's stable across lane-scan refreshes.
# Persists until restored via the "Show dismissed" toggle.
#
# Schema: state["iuq_dismissed"] = {card_id: "YYYY-MM-DD"}

def is_iuq_dismissed(card_id):
    if not card_id:
        return False
    return str(card_id) in (_load().get("iuq_dismissed", {}) or {})


def dismiss_iuq(card_id):
    """Hide this card's IUQ row going forward. Persists until restored."""
    cid = str(card_id or "").strip()
    if not cid:
        return
    data = _load()
    data.setdefault("iuq_dismissed", {})[cid] = \
        datetime.today().strftime("%Y-%m-%d")
    _save(data)


def undismiss_iuq(card_id):
    """Restore a single dismissed IUQ card to the visible queue."""
    cid = str(card_id or "").strip()
    if not cid:
        return
    data = _load()
    rec = data.get("iuq_dismissed", {})
    if cid in rec:
        rec.pop(cid, None)
        _save(data)


def list_iuq_dismissals():
    """Return [(card_id, dismissed_yyyy_mm_dd), ...] newest-first."""
    rec = _load().get("iuq_dismissed", {}) or {}
    return sorted(rec.items(), key=lambda kv: kv[1], reverse=True)


# ── Audit-finding Trello comment posts ───────────────────────────────────────
#
# Tracks "I posted a 'CIF missing' comment to this card on this date" so the
# per-row 💬 Comment button can't spam the same finding to a card every
# time the user re-runs the audit. Persisted across sessions (lives in
# state.json) so a fresh launcher start still sees recent posts.
#
# Schema: state["audit_comments"][f"{client}::{issue_key}"] = "MM-DD-YYYY"

def _audit_comment_key(client, issue_key):
    # Canonicalize the client portion so the same finding doesn't double-fire
    # the nag just because the user re-ran the audit under a different
    # client-name representation (carrier suffix, whitespace, casing).
    return f"{_canon_pin_key(client)}::{_esc(issue_key)}"


def get_audit_comment_date(client, issue_key):
    """Return the MM-DD-YYYY date a comment was posted for this
    client+issue, or "" if none."""
    if not client or not issue_key:
        return ""
    rec = _load().get("audit_comments", {})
    return rec.get(_audit_comment_key(client, issue_key), "")


def audit_comment_posted_within(client, issue_key, days=3):
    """True if the comment was posted within the last `days` days.
    Used to grey-out the 💬 button after a recent post so the user can
    see at a glance that the card already got the nag."""
    d = get_audit_comment_date(client, issue_key)
    if not d:
        return False
    try:
        ts = datetime.strptime(d, "%m-%d-%Y").timestamp()
    except Exception:
        return False
    return ts >= (time.time() - days * 86400)


def mark_audit_comment_posted(client, issue_key, run_date=None):
    """Record that a Trello comment was posted for this client+issue
    on `run_date` (or today). Overwrites any prior date — only the
    most recent post matters for the guard window."""
    if not client or not issue_key:
        return
    date_str = run_date or datetime.today().strftime("%m-%d-%Y")
    data = _load()
    data.setdefault("audit_comments", {})[
        _audit_comment_key(client, issue_key)] = date_str
    _save(data)


# ── APA per-item Teams-message notes ─────────────────────────────────────────
#
# Free-form per-row notes for Audit Dispute / Audit Rejection rows. The note
# is NEVER written into the .docx audit — it lives in state.json and gets
# appended to the Teams message that goes out to the estimator (per-item,
# per-section, per-estimator, and Send-All paths all read it). Lets the user
# attach context like "see email Chain" or a list of bad line items without
# polluting the daily doc.
#
# Schema: state["apa_message_notes"][f"{canon_client}::{section}"] = "text"

def _apa_message_note_key(client, section):
    return f"{_canon_pin_key(client)}::{(section or '').strip()}"


def get_apa_message_note(client, section):
    if not client or not section:
        return ""
    rec = _load().get("apa_message_notes", {})
    if not isinstance(rec, dict):
        return ""
    return rec.get(_apa_message_note_key(client, section), "")


def set_apa_message_note(client, section, text):
    """Persist a per-(client, section) Teams-message note. Pass an empty
    or whitespace-only `text` to clear the entry."""
    if not client or not section:
        return
    key = _apa_message_note_key(client, section)
    data = _load()
    notes = data.get("apa_message_notes")
    if not isinstance(notes, dict):
        notes = {}
        data["apa_message_notes"] = notes
    val = (text or "").strip()
    if val:
        notes[key] = val
    else:
        notes.pop(key, None)
    _save(data)


def has_apa_message_note(client, section):
    return bool(get_apa_message_note(client, section).strip())


# ── Per-client free-form notes ───────────────────────────────────────────────

def get_note(client):
    notes = _load().get("notes", {})
    # Tolerate either canonical or raw-name legacy entries — readers in
    # the audit/snapshot pin-detection paths invoke this as a fallback
    # alongside the year-scoped job_notes_gui store.
    return (notes.get(_canon_pin_key(client))
            or notes.get(client) or "")


def has_note(client):
    return bool(get_note(client).strip())


# ── Estimator → Teams email map (for auto-message) ───────────────────────────

def get_estimator_emails():
    return _load().get("estimator_emails", {})


def get_estimator_email(name):
    return _load().get("estimator_emails", {}).get(name, "")


def set_estimator_email(name, email):
    state  = _load()
    emails = state.setdefault("estimator_emails", {})
    if email and email.strip():
        emails[name] = email.strip()
    else:
        emails.pop(name, None)
    _save(state)


# ── Escalation contacts (Sam/Zac/George) + sent tracking ────────────────────

def get_escalation_emails():
    return _load().get("escalation_emails", {})


def get_escalation_email(role):
    return _load().get("escalation_emails", {}).get(role, "")


def set_escalation_email(role, email):
    state = _load()
    emails = state.setdefault("escalation_emails", {})
    if email and email.strip():
        emails[role] = email.strip()
    else:
        emails.pop(role, None)
    _save(state)


def _escalation_key(run_date, client):
    return f"{_esc(run_date)}::{_esc(client)}"


def is_escalated(run_date, client):
    return _escalation_key(run_date, client) in _load().get("escalations_sent", {})


def set_escalated(run_date, client, sent=True):
    state = _load()
    sent_map = state.setdefault("escalations_sent", {})
    key = _escalation_key(run_date, client)
    if sent:
        sent_map[key] = time.time()
    else:
        sent_map.pop(key, None)
    _save(state)


# ── APA EOD email recipients (single shared list) ────────────────────────────

def get_eod_recipients():
    """List of email addresses for the daily APA EOD summary."""
    val = _load().get("apa_eod_recipients", [])
    return val if isinstance(val, list) else []


def set_eod_recipients(emails):
    state = _load()
    cleaned = [e.strip() for e in (emails or []) if e and e.strip()]
    state["apa_eod_recipients"] = cleaned
    _save(state)


# ── Per-client commercial flag (sticky across all audits) ────────────────────
#
# Keys are canonicalized via `_canon_pin_key` (case-folded, carrier-suffix
# stripped, whitespace collapsed) so the same job set as commercial in one
# tool is recognised everywhere — no duplicate "Smith Construction" vs
# "Smith Construction - Allstate" entries.

def is_commercial(client):
    com = _load().get("commercial", {})
    key = _canon_pin_key(client)
    # Tolerate any legacy non-canonical entries by also probing the raw key.
    return bool(com.get(key) or com.get(client))


def set_commercial(client, checked):
    state = _load()
    com   = state.setdefault("commercial", {})
    key = _canon_pin_key(client)
    if checked:
        com[key] = True
    else:
        com.pop(key, None)
        com.pop(client, None)
    _save(state)


# ── Self-pay ────────────────────────────────────────────────────────────────
#
# The mirror image of `commercial`: that flag REMOVES the four insurance
# forms, this one ADDS two. A self-pay job is a home-improvement contract
# with a consumer, so California requires the contract itself and the
# 3-Day Right to Cancel notice — neither of which an insurance job needs.

def is_self_pay(client):
    sp = _load().get("self_pay", {})
    key = _canon_pin_key(client)
    return bool(sp.get(key) or sp.get(client))


def set_self_pay(client, checked):
    state = _load()
    sp = state.setdefault("self_pay", {})
    key = _canon_pin_key(client)
    if checked:
        sp[key] = True
    else:
        sp.pop(key, None)
        sp.pop(client, None)
    _save(state)


# ── Window geometry per app (size + position survive close) ──────────────────

def get_geometry(app_id):
    return _load().get("window_geometry", {}).get(app_id)


def set_geometry(app_id, geo):
    state = _load()
    geos  = state.setdefault("window_geometry", {})
    if geo:
        geos[app_id] = geo
    _save(state)


# ── PanedWindow sash positions ─────────────────────────────────────────────
# `key` is "<app_id>:<paned_id>"; value is a list of integer sash x/y offsets.
def get_sash_positions(key):
    val = _load().get("paned_sash", {}).get(key)
    if isinstance(val, list) and all(isinstance(v, int) for v in val):
        return val
    return None


def set_sash_positions(key, positions):
    state = _load()
    sashes = state.setdefault("paned_sash", {})
    if positions:
        sashes[key] = list(positions)
    else:
        sashes.pop(key, None)
    _save(state)


# ── APA franchise tags ─────────────────────────────────────────────────────
# Local-only labels; never written to the .docx. Tag list is the user's
# franchise roster; tags map a normalized client text to a franchise name.
def get_franchise_list():
    val = _load().get("apa_franchises", [])
    return val if isinstance(val, list) else []


def set_franchise_list(items):
    state = _load()
    cleaned = [str(x).strip() for x in (items or []) if str(x).strip()]
    state["apa_franchises"] = cleaned
    _save(state)


# ── APA "extended" history ────────────────────────────────────────────────
# Per-client running count of times the user has set an APA row's status
# to "extended". The audit panel already surfaces a recurring badge for
# jobs that get flagged for missing items repeatedly; this mirrors that
# pattern in APA so the user can spot jobs that keep getting extended
# instead of closed out.
#
# Shape: { canonical_client_key: { "count": int, "dates": [ISO str, ...] } }
# Dates capped at the last 10 to keep state.json bounded.

def get_apa_extended_history():
    val = _load().get("apa_extended_history", {})
    return val if isinstance(val, dict) else {}


def get_apa_extended_count(client_key):
    """Quick read for the row's badge — returns 0 when there's no entry."""
    key = (client_key or "").strip()
    if not key:
        return 0
    entry = get_apa_extended_history().get(key)
    if not isinstance(entry, dict):
        return 0
    try:
        return int(entry.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def bump_apa_extended(client_key):
    """Record a transition into 'extended' for `client_key`. Returns the
    new count. Pass the SAME canonical key the franchise tag uses so the
    badge tracks across multi-day reads of the same job."""
    key = (client_key or "").strip()
    if not key:
        return 0
    state = _load()
    history = state.setdefault("apa_extended_history", {})
    entry = history.get(key)
    if not isinstance(entry, dict):
        entry = {"count": 0, "dates": []}
    cur = 0
    try:
        cur = int(entry.get("count") or 0)
    except (TypeError, ValueError):
        cur = 0
    entry["count"] = cur + 1
    dates = entry.get("dates")
    if not isinstance(dates, list):
        dates = []
    dates.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    # Keep last 10 — enough for the tooltip to show a real pattern,
    # bounded so state.json doesn't grow without limit on a job that
    # somehow loops forever.
    entry["dates"] = dates[-10:]
    history[key] = entry
    state["apa_extended_history"] = history
    _save(state)
    return entry["count"]


def reset_apa_extended(client_key):
    """Drop the recurring count + history for `client_key`. Use after
    the job is finally closed out so the badge clears."""
    key = (client_key or "").strip()
    if not key:
        return
    state = _load()
    history = state.get("apa_extended_history") or {}
    if isinstance(history, dict) and key in history:
        history.pop(key, None)
        state["apa_extended_history"] = history
        _save(state)


def get_franchise_tags():
    val = _load().get("apa_franchise_tags", {})
    return val if isinstance(val, dict) else {}


def set_franchise_tag(client_key, franchise):
    """Set or clear the franchise label for a client (key already normalized)."""
    state = _load()
    tags = state.setdefault("apa_franchise_tags", {})
    if franchise:
        tags[client_key] = franchise
    else:
        tags.pop(client_key, None)
    _save(state)


def migrate_franchise_keys(canon_func):
    """One-shot rewrite of `apa_franchise_tags` keys through `canon_func`.

    The old _franchise_key only normalized whitespace/case, so the same
    job was stored under multiple keys when its text varied between
    " - Carrier" / "- Carrier" / "(Contents) - Carrier" / etc. Callers
    pass the current canonicalizer; duplicate keys merge into one entry
    (latest non-empty value wins on collision).

    Runs once per upgrade — guarded by `apa_franchise_keys_canon_v` so
    subsequent loads are no-ops. Returns the number of keys collapsed."""
    CANON_VERSION = 1
    state = _load()
    if state.get("apa_franchise_keys_canon_v") == CANON_VERSION:
        return 0
    tags = state.get("apa_franchise_tags") or {}
    if not isinstance(tags, dict):
        state["apa_franchise_keys_canon_v"] = CANON_VERSION
        _save(state)
        return 0
    rebuilt: dict[str, str] = {}
    collapsed = 0
    for raw_key, val in tags.items():
        try:
            new_key = canon_func(raw_key)
        except Exception:
            new_key = raw_key
        if not new_key:
            collapsed += 1
            continue
        if new_key in rebuilt:
            # Latest non-empty value wins. With tag values typically
            # identical across variants (same job → same franchise), the
            # tiebreak rarely matters; this just prevents silent data loss.
            if val:
                rebuilt[new_key] = val
            collapsed += 1
        else:
            rebuilt[new_key] = val
    state["apa_franchise_tags"] = rebuilt
    state["apa_franchise_keys_canon_v"] = CANON_VERSION
    _save(state)
    return collapsed


def get_apa_franchise_filter():
    """Last selected franchise filter for the APA panel ('' = All)."""
    val = _load().get("apa_franchise_filter", "")
    return val if isinstance(val, str) else ""


def set_apa_franchise_filter(value):
    state = _load()
    state["apa_franchise_filter"] = str(value or "")
    _save(state)


# ── Per-client SharePoint match rejects ─────────────────────────────────────
# When the SP-folder substring search pulls a wrong job (e.g. "Maldanado,
# Joseph" matching "aldana" for client "Celia Aldana"), the user can mark
# that folder as the wrong job and we hide it on every future audit.
# Keyed by SP folder path so the rejection is precise — moving the folder
# breaks the rejection naturally, which is the right behavior.

def get_sp_match_rejects(client):
    """Return the set of SP folder paths the user has rejected for this client."""
    val = _load().get("sp_match_rejects", {}).get(client, [])
    return set(val) if isinstance(val, list) else set()


def add_sp_match_reject(client, path):
    if not client or not path:
        return
    state = _load()
    rejects = state.setdefault("sp_match_rejects", {})
    bucket = rejects.get(client, [])
    if not isinstance(bucket, list):
        bucket = []
    if path not in bucket:
        bucket.append(path)
    rejects[client] = bucket
    _save(state)


def clear_sp_match_rejects(client):
    state = _load()
    rejects = state.setdefault("sp_match_rejects", {})
    rejects.pop(client, None)
    _save(state)


# ── Per-client SharePoint match overrides ───────────────────────────────────
# Inverse of rejects: SP folder paths the user has manually pointed at this
# client. The auto-matcher scans by client-name substring, so a folder named
# "Recon Photos 4-15" (no client name) gets missed even though the user knows
# it belongs here. Overrides force-include those folders on every audit until
# the user removes them.

def _migrate_sp_match_override_keys(state):
    """One-shot canonicalization sweep over sp_match_overrides.

    Pre-2026-05-19 the dict was keyed by raw client strings, so a pin
    set from APA ("Sanchez, Anthony - State Farm") was invisible to a
    later audit lookup ("Sanchez, Anthony"). Re-keys every legacy
    entry under `_canon_pin_key(name)` and merges buckets whose
    canonical key collides. Idempotent — re-running finds nothing to
    migrate the second time."""
    overrides = state.get("sp_match_overrides", {})
    if not isinstance(overrides, dict) or not overrides:
        return False
    migrated: dict[str, list[str]] = {}
    needs_save = False
    for raw_key, bucket in overrides.items():
        if not isinstance(bucket, list):
            continue
        canon = _canon_pin_key(raw_key)
        if not canon:
            continue
        if canon != raw_key:
            needs_save = True
        cur = migrated.get(canon, [])
        for p in bucket:
            if p and p not in cur:
                cur.append(p)
        migrated[canon] = cur
    if needs_save:
        state["sp_match_overrides"] = migrated
    return needs_save


def get_sp_match_overrides(client):
    """Return the list of SP folder paths the user has manually attached
    to this client (in insertion order, so the audit dialog can render
    them in the order the user added them).

    Keys are canonicalized via `_canon_pin_key` (case-folded,
    whitespace-collapsed, " - Carrier" suffix stripped) — same key
    function `set_folder_path` / `get_folder_path` use, so a pin set
    from APA ("Sanchez, Anthony - State Farm") resolves to the same
    entry the audit looks up ("Sanchez, Anthony"). Previously these
    used raw client strings as keys, which silently lost overrides
    when the surfaces disagreed on punctuation."""
    key = _canon_pin_key(client)
    if not key:
        return []
    state = _load()
    if _migrate_sp_match_override_keys(state):
        _save(state)
    val = state.get("sp_match_overrides", {}).get(key, [])
    return list(val) if isinstance(val, list) else []


def add_sp_match_override(client, path):
    """Pin a manual SP folder override under the canonical key for
    `client` (see `get_sp_match_overrides` for why). Drains the
    pre-canonicalization legacy entries in the same save when any
    are found."""
    if not client or not path:
        return
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    _migrate_sp_match_override_keys(state)
    overrides = state.setdefault("sp_match_overrides", {})
    bucket = overrides.get(key, [])
    if not isinstance(bucket, list):
        bucket = []
    if path not in bucket:
        bucket.append(path)
    overrides[key] = bucket
    _save(state)


def remove_sp_match_override(client, path):
    """Remove `path` from `client`'s SP-override bucket. Canonicalized
    lookup so the remove call matches whichever surface wrote the
    pin originally."""
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    _migrate_sp_match_override_keys(state)
    overrides = state.setdefault("sp_match_overrides", {})
    bucket = overrides.get(key, [])
    if isinstance(bucket, list) and path in bucket:
        bucket.remove(path)
        if bucket:
            overrides[key] = bucket
        else:
            overrides.pop(key, None)
        _save(state)


def clear_sp_match_overrides(client):
    state = _load()
    overrides = state.setdefault("sp_match_overrides", {})
    overrides.pop(client, None)
    _save(state)


# ── User-added tech roster (merged into audit_logic.TECH_PATTERN) ────────────

def get_user_techs():
    """Return {"names": [...], "abbrev": {INITIALS: NAME, ...}} for techs
    the user has added through the roster dialog. Names are stored as the
    user typed them so they can include any spacing/casing the dispatch
    line uses."""
    ut = _load().get("user_techs", {}) or {}
    return {
        "names":  list(ut.get("names", []) or []),
        "abbrev": dict(ut.get("abbrev", {}) or {}),
    }


def set_user_techs(names, abbrev):
    """Replace the entire user-tech list. Callers should call
    `audit_logic.rebuild_tech_pattern()` afterward so the live regex picks
    up the change without restarting."""
    state = _load()
    clean_names = []
    for n in (names or []):
        if n is None:
            continue
        s = str(n).strip()
        if s:
            clean_names.append(s)
    clean_abbrev = {}
    for k, v in (abbrev or {}).items():
        if k is None or v is None:
            continue
        ks = str(k).strip().upper()
        vs = str(v).strip()
        if ks and vs:
            clean_abbrev[ks] = vs
    state["user_techs"] = {"names": clean_names, "abbrev": clean_abbrev}
    _save(state)


def user_techs_seeded():
    """True once the built-in roster has been migrated into the editable
    user_techs store. After that, audit_logic builds TECH_PATTERN from
    user_techs ALONE, so every tech (formerly-hardcoded included) is
    removable/adjustable and a removal actually sticks."""
    return bool(_load().get("user_techs_seeded"))


def mark_user_techs_seeded():
    """Record that the one-time builtin→user_techs migration has run."""
    state = _load()
    state["user_techs_seeded"] = True
    _save(state)


# ── CompanyCam sync state (per project) ─────────────────────────────────────
# Tracks what we've already pulled from a CompanyCam project so the "any new
# photos?" check and the downloader don't re-fetch the whole history each run.
# `last_captured_at` is the newest photo capture time (unix seconds) we've seen;
# `job` is a human label (the client name) purely for diagnostics.

def get_companycam_seen(project_id):
    """Return {"last_captured_at": int|None, "job": str} for a CompanyCam
    project id — the high-water mark for its photo sync."""
    pid = str(project_id or "").strip()
    if not pid:
        return {"last_captured_at": None, "job": ""}
    bucket = _load().get("companycam_seen", {}) or {}
    entry = bucket.get(pid) or {}
    return {
        "last_captured_at": entry.get("last_captured_at"),
        "job": entry.get("job", ""),
    }


def set_companycam_seen(project_id, last_captured_at, job=""):
    """Persist the newest photo capture time pulled for a project. Only
    advances the mark (never rewinds), so a partial/older re-scan can't lose
    ground already covered."""
    pid = str(project_id or "").strip()
    if not pid:
        return
    state = _load()
    bucket = state.setdefault("companycam_seen", {})
    prev = (bucket.get(pid) or {}).get("last_captured_at")
    try:
        newest = int(last_captured_at) if last_captured_at is not None else None
    except (TypeError, ValueError):
        newest = None
    if prev is not None and newest is not None:
        newest = max(int(prev), newest)
    elif newest is None:
        newest = prev
    bucket[pid] = {"last_captured_at": newest, "job": job or
                   (bucket.get(pid) or {}).get("job", "")}
    _save(state)


# ── Audit result cache (per run-date + client + unit) ───────────────────────
# Re-running an audit on the same run-doc walks the same X:\ tree for jobs
# that haven't changed since the last run. The cache stores the form/photo
# check result keyed by (run_date, normalized client, unit), with a folder
# mtime "signature" so we can detect changes. Flagged results are NEVER
# cached — the user re-runs the audit specifically to re-check them.

_AUDIT_CACHE_TTL_DAYS = 14


def _audit_cache_key(run_date, client, unit):
    rd  = (run_date or "").strip()
    cl  = " ".join((client or "").lower().split())
    un  = (str(unit) if unit is not None else "").strip().lower()
    return f"{_esc(rd)}::{_esc(cl)}::{_esc(un)}"


def get_audit_cache_entry(run_date, client, unit):
    """Return the cached audit entry dict or None.

    Entry shape: {"path": str, "sig": float, "result": dict, "ts": float}
    Caller is responsible for validating that path/sig still match disk
    state before reusing result.
    """
    if not run_date or not client:
        return None
    bucket = _load().get("audit_cache", {})
    return bucket.get(_audit_cache_key(run_date, client, unit))


def set_audit_cache_entry(run_date, client, unit, path, sig, result):
    """Store an audit result. Skips empty/flagged results so re-runs always
    re-check anything the user might be waiting on."""
    if not run_date or not client or not path:
        return
    if not isinstance(result, dict):
        return
    if result.get("flagged"):
        return
    state = _load()
    bucket = state.setdefault("audit_cache", {})
    bucket[_audit_cache_key(run_date, client, unit)] = {
        "path":   path,
        "sig":    sig,
        "result": result,
        "ts":     time.time(),
    }
    _save(state)


def prune_audit_cache(keep_days=_AUDIT_CACHE_TTL_DAYS):
    """Drop cache entries older than N days. Called from audit_logic on
    each bulk run so the cache doesn't grow without bound."""
    state = _load()
    bucket = state.get("audit_cache", {})
    if not bucket:
        return
    cutoff = time.time() - keep_days * 86400
    dropped = [k for k, v in bucket.items()
               if not isinstance(v, dict) or float(v.get("ts", 0)) < cutoff]
    if not dropped:
        return
    for k in dropped:
        bucket.pop(k, None)
    _save(state)


# ── Per-job activity ledger (day-by-day photo requirements) ──────────────────
# Records which photographable activities (Demo, Mold Prep, …) happened on
# which dates for each job, so the audit can accumulate day-by-day photo
# requirements ("Demo photos" day 1, "Demo day 2 photos", …). Keyed by the
# canonical client pin key so it lines up with folder / Trello pins.

def record_job_activity(client, date_iso, activity):
    """Append (date_iso, activity) to a client's activity ledger, deduped
    by (date, activity). `date_iso` is 'YYYY-MM-DD'. Safe to call on every
    audit run — a repeat call for the same date+activity is a no-op."""
    if not client or not date_iso or not activity:
        return
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    log = state.setdefault("job_activity_log", {})
    client_log = log.setdefault(key, {})
    dates = client_log.setdefault(activity, [])
    if date_iso not in dates:
        dates.append(date_iso)
        dates.sort()
        _save(state)


def get_job_activity_log(client):
    """Return {activity: [date_iso, ...]} for a client, or {} when none."""
    key = _canon_pin_key(client)
    if not key:
        return {}
    log = _load().get("job_activity_log", {})
    val = log.get(key, {})
    return {k: list(v) for k, v in val.items()} if isinstance(val, dict) else {}


def clear_job_activity_log(client):
    """Drop a client's entire activity ledger (e.g. job closed out)."""
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    log = state.get("job_activity_log", {})
    if key in log:
        log.pop(key, None)
        _save(state)


# ── Per-client folder path overrides (set when user uses Find Folder) ────────

def _pin_lookup_keys(client):
    """Ordered, de-duped canon keys to try when LOOKING UP a folder pin.

    A pin lands under whatever name ORDER the pinning surface used:
      • "Linda Valek"  (IUQ/APA card title, First Last)
      • "Valek, Linda" (audit run-doc, Last, First)
      • "Valek Linda"  (bare OD folder name, Last First, no comma)
    `_canon_pin_key` normalizes case / whitespace / " - Carrier" but NOT
    name order, so a pin written under one order is invisible to a lookup
    in another. Symptom (Linda Valek, 2026-06-12): the OD folder opened
    fine (open-OD has a row-path hint) but WC/SP import said "no OD folder"
    because `do_import` only had `get_folder_path` to go on and the card's
    "Valek Linda" form didn't match the stored "linda valek" key.

    This returns the direct key first, then name-order variants, so GET
    reconciles them. We deliberately DON'T change the STORED key (that
    would orphan every existing pin) — only widen the lookup.
    """
    base = _canon_pin_key(client)
    if not base:
        return []
    keys = [base]

    def _add(k):
        if k and k not in keys:
            keys.append(k)

    if "," in base:
        # "last, first" → also try "first last" / "last first".
        head, _, tail = base.partition(",")
        head, tail = head.strip(), tail.strip()
        if head and tail:
            _add(f"{tail} {head}")
            _add(f"{head} {tail}")
    else:
        toks = base.split()
        if len(toks) == 2:
            # Two-token name with no comma — try the reverse order plus
            # both comma forms. Covers First↔Last drift between the card
            # title and the OD folder name.
            a, b = toks
            _add(f"{b} {a}")
            _add(f"{a}, {b}")
            _add(f"{b}, {a}")
    return keys


def get_folder_path(client):
    """Return a previously-picked folder for this client, or None.

    Keys are canonicalized via `_canon_pin_key` (case-folded,
    whitespace-collapsed, " - Carrier" suffix stripped) so a pin set
    from any surface — audit ("Sanchez, Anthony"), APA ("Sanchez,
    Anthony - State Farm"), IUQ card title (same as APA) — resolves
    to the same entry. Without this, "Anthony Sanchez on the job but
    Antonio on the OD" — the pin set from one row was silently
    invisible to the next audit run.

    Lookup also tries name-ORDER variants (`_pin_lookup_keys`) so a pin
    stored as "linda valek" still resolves a "Valek Linda" lookup — the
    "linked but import says no OD" class of bug.
    """
    fp = _load().get("folder_paths", {})
    for key in _pin_lookup_keys(client):
        if key in fp:
            return fp[key]
    return None


def set_folder_path(client, path):
    """Pin (or clear, when `path` is falsy) the OD folder override for
    this client. Uses the same canonical key as `get_folder_path`."""
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    paths = state.setdefault("folder_paths", {})
    if path:
        paths[key] = path
    else:
        paths.pop(key, None)
    _save(state)
    # Teach the shared jobs graph: pinning a folder is the definitive
    # "this spelling ↔ this job" moment. resolve_and_link ties the folder
    # to the job AND — when that folder already belongs to a job filed
    # under a DIFFERENT spelling — records `client` as an alias, so every
    # other tool then resolves this spelling to the same job instead of
    # re-guessing by name. Best-effort; a DB hiccup never blocks the pin.
    if path:
        try:
            import ems_db
            ems_db.resolve_and_link(client, folder_path=path,
                                    create=True, source="folder_pin")
        except Exception:
            pass


# ── Per-client search aliases (alternate names for SP / folder / Trello) ───
#
# When a job's spreadsheet/run-doc name doesn't line up with how the folder
# is filed (commercial jobs filed under business name, address-only folders,
# nicknames, claim numbers, etc.), the user can add alias names here. Every
# search-by-name lookup (SP folder scan, audit folder lookup, Trello fuzzy
# match) tries the canonical name first then each alias.

def get_search_aliases(client):
    """Return the list of alias names registered for `client`. Empty list
    when none. Always returns a fresh list — callers can mutate freely."""
    raw = _load().get("search_aliases", {}).get(client, [])
    if not raw:
        return []
    # Defensive: legacy entries may have stored a single string. Coerce.
    if isinstance(raw, str):
        return [raw]
    return [str(x).strip() for x in raw if str(x).strip()]


def set_search_aliases(client, aliases):
    """Replace the full alias list for `client`. Pass an empty list (or
    None) to clear. Whitespace-only entries are dropped. De-duped
    case-insensitively while preserving insertion order — first
    occurrence wins."""
    state = _load()
    bucket = state.setdefault("search_aliases", {})
    cleaned = []
    seen = set()
    for a in (aliases or []):
        s = str(a).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    if cleaned:
        bucket[client] = cleaned
    else:
        bucket.pop(client, None)
    _save(state)


def client_search_terms(client):
    """Return [`client`, *aliases] — the full set of names every search-by-
    name lookup should try for this client. The canonical name is always
    first so callers that stop at the first hit still behave correctly
    when no aliases are configured. De-duped case-insensitively."""
    out = []
    seen = set()
    for term in (client, *get_search_aliases(client)):
        s = (term or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ── Trello card_id pinning ──────────────────────────────────────────────────
# Once a user picks the right Trello card for a client (via the "Pin to
# Trello card…" right-click), we save the card id(s) here so every later
# read/post against that client goes straight to the card without re-running
# fuzzy search. Card ids are stable across renames and lane moves.
#
# A single client can be pinned to MULTIPLE cards — the same job often
# lives on multiple boards (e.g. WIP + AR Board) and the user wants both
# streams in the job-notes view. Storage is a list per client; the
# `_id` (singular) accessor returns the first entry as a convenience for
# legacy callers that only need an arbitrary representative card.

def get_trello_card_ids(client):
    """Return the list of pinned Trello card ids for `client`, or [] when
    not pinned. Always a list — empty if no pin, length 1 for the common
    single-card case, longer when the user linked multiple boards.

    Lookup is case/whitespace/carrier-suffix-insensitive: APA's
    'Doe, John - State Farm' and the audit's 'Doe, John' share storage,
    so a pin set from either surface is visible from both."""
    key = _canon_pin_key(client)
    if not key:
        return []
    raw = _load().get("trello_card_ids", {}).get(key)
    if not raw:
        return []
    if isinstance(raw, str):
        # Defensive: schema migration in _read_from_disk normally
        # converts strings to lists, but a hot-path concurrent edit
        # could land here mid-flight. Cheap to handle both.
        return [raw]
    return list(raw)


def get_trello_card_id(client):
    """Convenience: return the FIRST pinned card id, or None.
    Use this when one representative card is enough (link-out, fuzzy
    fallbacks). For the job-notes feed that needs every linked card,
    call get_trello_card_ids."""
    ids = get_trello_card_ids(client)
    return ids[0] if ids else None


def set_trello_card_ids(client, card_ids):
    """Replace the list of pinned card ids for `client`. Empty list /
    None unpins entirely. Key is canonicalized so the same job pinned
    from APA ('Doe, John - State Farm') and from the audit ('Doe, John')
    converges on a single entry."""
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    pins = state.setdefault("trello_card_ids", {})
    cleaned = [c for c in (card_ids or []) if c]
    if cleaned:
        # Dedupe while preserving caller-supplied order (the picker order
        # is meaningful — first card is the primary / default for posts).
        seen = set()
        deduped = []
        for c in cleaned:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        pins[key] = deduped
    else:
        pins.pop(key, None)
    _save(state)
    # Mirror into the shared jobs DB so every tool sees the pin without
    # consulting persistence.json directly, AND teach the identity graph:
    # a Trello card is a strong id, so if it already belongs to a job filed
    # under a different spelling, resolve_and_link aliases `client` to that
    # job instead of spawning a duplicate. Best-effort — a DB hiccup must
    # not block the pin write itself.
    try:
        import ems_db
        if cleaned:
            job = ems_db.resolve_and_link(client, trello_card=cleaned[0],
                                          create=True, source="trello_pin")
            job_key = job["canon_key"] if job else key
        else:
            found = ems_db.find_job_by_name(client)
            job_key = (found["canon_key"] if found
                       else ems_db.upsert_job(
                           display_name=(client or "").strip() or key))
        # Mirror the full card list onto the resolved job (replace-set).
        ems_db.remove_link(job_key, "trello_card")
        for cid in cleaned:
            ems_db.set_link(job_key, "trello_card", cid,
                            added_by="persistence.set_trello_card_ids")
        # Adopt the Trello card's NAME as the job's identity (the
        # 2026-07-22 rule: jobs are represented by their card name). Fetch
        # the primary card once, name a canonical job after it, and fold
        # the just-pinned spelling into it so all spellings converge on
        # the one card-named job. Best-effort — a Trello hiccup or a
        # missing card must never block the pin write.
        if cleaned:
            try:
                import trello_client as _tc
                _card = _tc.get_card(cleaned[0], actions_limit=0)
                _nm = (_card or {}).get("name", "") or ""
                _ck = ems_db.canon_key(_nm) if _nm else ""
                if _ck:
                    ems_db.upsert_job(display_name=_nm)
                    for cid in cleaned:
                        ems_db.set_link(_ck, "trello_card", cid,
                                        added_by="pin_card_name")
                    ems_db.add_alias(_ck, client, source="trello_pin")
                    if _ck != job_key:
                        ems_db.merge_jobs(_ck, [job_key])
            except Exception:
                pass
    except Exception:
        pass


def set_trello_card_id(client, card_id):
    """Single-card convenience that wraps set_trello_card_ids. Replaces
    any existing pins (use set_trello_card_ids directly to add to a
    multi-card list without dropping the others)."""
    set_trello_card_ids(client, [card_id] if card_id else [])


def backfill_job_graph():
    """One-time seed of the ems_db identity graph from EXISTING folder +
    Trello pins, so auto-linking benefits from history — not just pins made
    from now on. Every pin is ground truth ('this spelling ↔ this folder /
    card'), so replaying them establishes the strong-id links that let a
    differently-spelled reference auto-alias later.

    Idempotent (resolve_and_link + set_link are), so it's safe to run more
    than once. Returns {folders, cards, jobs} counts. Best-effort per
    entry — a bad row is skipped, never fatal."""
    try:
        import ems_db
    except Exception:
        return {"folders": 0, "cards": 0, "jobs": 0}
    state = _load()
    folders = cards = 0
    touched = set()
    for key, path in (state.get("folder_paths") or {}).items():
        if not (key and path):
            continue
        try:
            job = ems_db.resolve_and_link(key, folder_path=path,
                                          create=True, source="backfill_folder")
            if job:
                touched.add(job["canon_key"])
                folders += 1
        except Exception:
            pass
    for key, cids in (state.get("trello_card_ids") or {}).items():
        cid_list = cids if isinstance(cids, list) else ([cids] if cids else [])
        cid_list = [c for c in cid_list if c]
        if not (key and cid_list):
            continue
        try:
            job = ems_db.resolve_and_link(key, trello_card=cid_list[0],
                                          create=True, source="backfill_trello")
            job_key = job["canon_key"] if job else ems_db.canon_key(key)
            touched.add(job_key)
            for c in cid_list:
                ems_db.set_link(job_key, "trello_card", c,
                                added_by="backfill_trello")
            cards += 1
        except Exception:
            pass
    return {"folders": folders, "cards": cards, "jobs": len(touched)}


# ── Starred (per-user followed) clients ───────────────────────────────────
# Persistent across days — a client the user explicitly starred in the
# audit panel will keep showing up in the ⭐ Starred mode regardless of
# whether they're on today's run-doc. Cleared by the user via the same
# star button (toggle off) or by clear_starred().

def is_starred(client):
    """True when `client` has been starred. Canon-keyed so 'Doe, John'
    and 'Doe, John - State Farm' resolve to the same star."""
    key = _canon_pin_key(client)
    if not key:
        return False
    state = _load()
    starred = state.get("starred_clients") or {}
    if isinstance(starred, list):
        return key in {_canon_pin_key(c) for c in starred}
    if isinstance(starred, dict):
        return bool(starred.get(key))
    return False


def set_starred(client, on=True):
    """Toggle a client's starred state. Stored under the canon pin key
    so APA-style carrier suffix variants converge."""
    key = _canon_pin_key(client)
    if not key:
        return
    state = _load()
    starred = state.get("starred_clients")
    if not isinstance(starred, dict):
        starred = {}
    if on:
        starred[key] = (client or "").strip() or key
    else:
        starred.pop(key, None)
    state["starred_clients"] = starred
    _save(state)


def get_starred_clients():
    """Return a list of starred client display names (the form the
    user originally starred). Order is insertion order via dict, which
    Python 3.7+ preserves — newer stars appear later."""
    state = _load()
    starred = state.get("starred_clients") or {}
    if isinstance(starred, list):
        return [str(c).strip() for c in starred if c]
    if isinstance(starred, dict):
        return [str(v).strip() for v in starred.values() if v]
    return []


def clear_starred():
    """Wipe every star. Use when the user wants to start fresh."""
    state = _load()
    state["starred_clients"] = {}
    _save(state)


# ── Initial Upload Queue cache (Trello WIP scan) ───────────────────────────
# Per-day snapshot of the Trello scan so the audit's Initial Upload Queue
# can render instantly during the day without re-hitting the Trello API on
# every panel reopen. Bucket-keyed by MM-DD-YYYY — anything older is
# considered stale and triggers a fresh fetch. Manual refresh in the UI
# also wipes the bucket so the next read goes to network.

# Bump this when _fetch_queue_from_trello changes its output shape /
# merge sources (APA pull-in, manual entries, lane additions). Any
# cache stamped with an older `schema` is treated as stale on read, so
# users don't keep seeing the pre-change card set until tomorrow's
# date roll. Mismatch counts as a cache miss → force-fetches fresh.
_INITIAL_QUEUE_CACHE_SCHEMA = 3


def get_initial_queue_cache():
    """Return today's cached card list, or None if missing/stale.
    Cache shape: {'date': 'MM-DD-YYYY', 'schema': int, 'cards': [...] }.
    Stale = cached date != today's date OR schema mismatch."""
    raw = _load().get("initial_queue_cache") or {}
    if not isinstance(raw, dict):
        return None
    cached_date = raw.get("date")
    today = datetime.today().strftime("%m-%d-%Y")
    if cached_date != today:
        return None
    if raw.get("schema") != _INITIAL_QUEUE_CACHE_SCHEMA:
        return None
    cards = raw.get("cards")
    if not isinstance(cards, list):
        return None
    return cards


def set_initial_queue_cache(cards):
    """Stamp `cards` into today's bucket. Pass [] to record a successful
    fetch that found nothing — distinguishes 'fetched, empty' from 'never
    fetched' so reopens within the day don't re-hit Trello unnecessarily."""
    state = _load()
    state["initial_queue_cache"] = {
        "date":   datetime.today().strftime("%m-%d-%Y"),
        "schema": _INITIAL_QUEUE_CACHE_SCHEMA,
        "cards":  list(cards or []),
    }
    _save(state)


def clear_initial_queue_cache():
    """Wipe the cache so the next read forces a fresh Trello fetch.
    Called by the queue's Refresh button."""
    state = _load()
    if "initial_queue_cache" in state:
        state.pop("initial_queue_cache", None)
        _save(state)


# ── Manual IUQ entries ─────────────────────────────────────────────────────
# Cards the user adds by hand to the Initial Upload Queue — for jobs whose
# Trello card lives in a board / lane the IUQ doesn't scan, or for ad-hoc
# intake work that never had a Trello card to begin with. Stored as a list
# so render order matches insertion order; case-insensitive client-name
# de-dupe lives in add_manual_iuq_card.

def get_manual_iuq_cards():
    """Return the persisted manual-add list. Each entry is a dict with
    at minimum {'client': str}; optional 'card_url' and 'card_id' wire
    the row to a Trello card so comments / autotick still work."""
    raw = _load().get("manual_iuq_cards") or []
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if isinstance(e, dict) and (e.get("client") or "").strip():
            out.append(dict(e))
    return out


def add_manual_iuq_card(client, *, card_url="", card_id=""):
    """Add (or update) a manual queue entry for `client`. Returns the
    full list after the change. Case-insensitive name match against
    existing entries so duplicates don't accumulate."""
    client = (client or "").strip()
    if not client:
        return get_manual_iuq_cards()
    state = _load()
    raw = state.get("manual_iuq_cards") or []
    if not isinstance(raw, list):
        raw = []
    lc = client.lower()
    out = []
    replaced = False
    for e in raw:
        if not isinstance(e, dict):
            continue
        if (e.get("client") or "").strip().lower() == lc:
            out.append({"client": client,
                        "card_url": (card_url or "").strip(),
                        "card_id": (card_id or "").strip()})
            replaced = True
        else:
            out.append(e)
    if not replaced:
        out.append({"client": client,
                    "card_url": (card_url or "").strip(),
                    "card_id": (card_id or "").strip()})
    state["manual_iuq_cards"] = out
    _save(state)
    return list(out)


def remove_manual_iuq_card(client):
    """Drop the manual entry for `client` (case-insensitive). No-op if
    the entry isn't there. Returns the surviving list."""
    client = (client or "").strip().lower()
    if not client:
        return get_manual_iuq_cards()
    state = _load()
    raw = state.get("manual_iuq_cards") or []
    if not isinstance(raw, list):
        return []
    out = [e for e in raw
           if isinstance(e, dict)
           and (e.get("client") or "").strip().lower() != client]
    state["manual_iuq_cards"] = out
    _save(state)
    return list(out)


# ── Stale-key cleanup ──────────────────────────────────────────────────────
# Persistence.json grows over time as clients come and go. This sweeps
# entries whose key no longer maps to a real folder under audit_base. Runs
# at most once per day (tracked via "last_stale_cleanup") so it doesn't
# repeat on every launcher restart.
def _all_known_clients(audit_base):
    """Walk audit_base/<year>/<client>/ to build a lowercased set of every
    client folder name we know about. Returns empty set if the base is
    unreachable so we DON'T accidentally wipe everything."""
    if not audit_base or not os.path.isdir(audit_base):
        return None
    seen = set()
    try:
        with os.scandir(audit_base) as it_yr:
            year_dirs = [ye for ye in it_yr if ye.is_dir()]
    except OSError:
        return None
    for ye in year_dirs:
        try:
            with os.scandir(ye.path) as it_cl:
                for cl in it_cl:
                    if cl.is_dir():
                        seen.add(cl.name.lower())
        except OSError:
            pass
    return seen


# ── Hygiene scan cache (workspace-wide scan results) ──────────────────────
# Persisting the last hygiene scan lets the panel render instantly on
# reopen instead of forcing a 4-5 minute Trello walk every time. Cache
# entry shape:
#   {"ts": iso_string, "hygiene": [...], "closeout": [...]}
# TTL is decided by the caller — get_hygiene_scan_cache returns None
# when the entry is older than `max_age_minutes` so callers don't have
# to interpret raw timestamps.

def get_hygiene_scan_cache(max_age_minutes=30):
    """Return ({"ts", "hygiene", "closeout"}, age_seconds) when the
    cached scan is fresh enough, else None. Empty result lists are
    valid (a scan that found nothing) — only a missing/stale entry
    returns None.
    """
    raw = get("hygiene_scan_cache") or {}       # sidecar, not state.json
    if not isinstance(raw, dict) or not raw.get("ts"):
        return None
    try:
        ts = datetime.fromisoformat(raw["ts"])
    except (TypeError, ValueError):
        return None
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc).replace(tzinfo=None)
    age = (now - ts).total_seconds()
    if age < 0:
        # Clock skew (machine time moved backward) — treat as stale
        # rather than serving a "fresh" cache from an impossible future.
        return None
    if age > max_age_minutes * 60:
        return None
    return ({
        "ts":         raw["ts"],
        "hygiene":    list(raw.get("hygiene") or []),
        "closeout":   list(raw.get("closeout") or []),
        "xa_apology": list(raw.get("xa_apology") or []),
        "xa_gaps":    list(raw.get("xa_gaps") or []),
        "ipr":        list(raw.get("ipr") or []),
        "estimates":  list(raw.get("estimates") or []),
        "weekly":     list(raw.get("weekly") or []),
    }, age)


def set_hygiene_scan_cache(hygiene, closeout, *, xa_apology=None,
                            xa_gaps=None, ipr=None, estimates=None,
                            weekly=None):
    """Persist the latest scan results. Lists are coerced to plain JSON-
    serializable shapes by virtue of being passed through json.dump on
    save — callers don't need to flatten."""
    from datetime import timezone as _tz
    set_value("hygiene_scan_cache", {          # sidecar, not state.json
        "ts": datetime.now(_tz.utc).replace(tzinfo=None).isoformat(
            timespec="seconds"),
        "hygiene":    list(hygiene or []),
        "closeout":   list(closeout or []),
        "xa_apology": list(xa_apology or []),
        "xa_gaps":    list(xa_gaps or []),
        "ipr":        list(ipr or []),
        "estimates":  list(estimates or []),
        "weekly":     list(weekly or []),
    })


# ── Estimate-request SLA tracker ──────────────────────────────────────────
# Inbound inquiries from adjusters (email) or carriers (XA notes). Stored
# keyed by stable request_id (hash of source+source_id+claim). Mutation is
# always whole-record — the estimate_requests module reads the record,
# mutates a copy, and calls set_estimate_request to persist.

def get_estimate_request(request_id):
    if not request_id:
        return None
    bucket = _load().get("estimate_requests", {})
    if not isinstance(bucket, dict):
        return None
    return bucket.get(request_id)


def set_estimate_request(request_id, record):
    """Upsert. `record` should be a dict shaped per estimate_requests.py
    docstring; we don't validate fields here so the module can evolve the
    schema without touching persistence."""
    if not request_id or not isinstance(record, dict):
        return
    state = _load()
    bucket = state.setdefault("estimate_requests", {})
    if not isinstance(bucket, dict):
        bucket = {}
        state["estimate_requests"] = bucket
    bucket[request_id] = record
    _save(state)


def iter_estimate_requests():
    """Yield (request_id, record) pairs for every stored request. Returns
    an empty iterator when the bucket is missing or malformed — callers
    can treat the result as always-safe to iterate."""
    bucket = _load().get("estimate_requests", {})
    if not isinstance(bucket, dict):
        return iter(())
    return iter(list(bucket.items()))


# ── Estimator → Trello handle mapping ─────────────────────────────────────
# Trello @mentions require the user's Trello handle (not their email).
# Stored separately from estimator_emails because the two aren't always
# the same person — some staff have a Trello account but the AT-mention
# goes to a different team handle.

def get_estimator_trello_handle(estimator):
    if not estimator:
        return ""
    bucket = _load().get("estimator_trello_handles", {})
    if not isinstance(bucket, dict):
        return ""
    return (bucket.get(estimator) or "").strip()


def set_estimator_trello_handle(estimator, handle):
    if not estimator:
        return
    state = _load()
    bucket = state.setdefault("estimator_trello_handles", {})
    if not isinstance(bucket, dict):
        bucket = {}
        state["estimator_trello_handles"] = bucket
    bucket[estimator] = (handle or "").strip().lstrip("@")
    _save(state)


def get_estimator_trello_handles():
    bucket = _load().get("estimator_trello_handles", {})
    return dict(bucket) if isinstance(bucket, dict) else {}


# ── Tech → email (Teams chat target) ─────────────────────────────────────
# Used by the audit panel's "📨 Request paperwork" action. The address
# becomes the `users=…` parameter on a `msteams:/l/chat/0/0` deeplink,
# which opens Teams with a chat to that user + the message pre-filled.
# Stored as canonical-display-name → email so the dispatcher can resolve
# whatever variant the run-doc parser produced (initials, partial, etc.)
# back to the right person.

def get_tech_emails():
    bucket = _load().get("tech_emails", {})
    return dict(bucket) if isinstance(bucket, dict) else {}


def get_tech_email(tech):
    if not tech:
        return ""
    bucket = _load().get("tech_emails", {})
    if not isinstance(bucket, dict):
        return ""
    # Direct hit
    direct = (bucket.get(tech) or "").strip()
    if direct:
        return direct
    # Case-insensitive fallback — run-doc may produce "mike escobar"
    # while the bucket has "Mike Escobar".
    tl = (tech or "").strip().lower()
    for name, email in bucket.items():
        if (name or "").strip().lower() == tl:
            return (email or "").strip()
    return ""


def set_tech_email(tech, email):
    if not tech:
        return
    state = _load()
    bucket = state.setdefault("tech_emails", {})
    if not isinstance(bucket, dict):
        bucket = {}
        state["tech_emails"] = bucket
    e = (email or "").strip()
    if e:
        bucket[tech] = e
    else:
        bucket.pop(tech, None)
    _save(state)


# ── Weekly check-in timestamps ────────────────────────────────────────────
# `weekly_note_sent: {card_id: iso}` — when the user last sent the weekly
# status note for that card. The Hygiene "📆 Weekly check-ins" section
# computes "due" from the gap between now and the stored timestamp
# (default 7 days). Cards with no entry surface as "never" / always due.

def get_weekly_note_sent(card_id):
    if not card_id:
        return None
    bucket = _load().get("weekly_note_sent", {})
    if not isinstance(bucket, dict):
        return None
    return bucket.get(card_id)


def set_weekly_note_sent(card_id, iso_ts=None):
    """Stamp `card_id` as weekly-note-sent right now (or at the passed
    iso timestamp). Pass `iso_ts=""` or `None` to clear the entry."""
    if not card_id:
        return
    state = _load()
    bucket = state.setdefault("weekly_note_sent", {})
    if not isinstance(bucket, dict):
        bucket = {}
        state["weekly_note_sent"] = bucket
    if iso_ts is None:
        from datetime import timezone as _tz
        iso_ts = (datetime.now(_tz.utc).replace(tzinfo=None)
                  .isoformat(timespec="seconds"))
    if iso_ts:
        bucket[card_id] = iso_ts
    else:
        bucket.pop(card_id, None)
    _save(state)


def get_weekly_notes_sent():
    bucket = _load().get("weekly_note_sent", {})
    return dict(bucket) if isinstance(bucket, dict) else {}


# ── IPR (Initial Photo Report) resolutions ─────────────────────────────────
# When the user clicks "Mark done" on an IPR row in the Hygiene panel
# we record the resolution so the next scan filters that comment out
# (key = card_id::comment_id, matching trello_hygiene._iter result keys).
# Auto-resolve via the user's "uploaded" follow-up comment runs upstream
# in ipr_tracker; this set is purely the manual-override path.

def _ipr_key(card_id, comment_id):
    return f"{_esc(card_id or '')}::{_esc(comment_id or '')}"


def is_ipr_resolved(card_id, comment_id):
    if not card_id or not comment_id:
        return False
    bucket = _load().get("ipr_resolved", {})
    if not isinstance(bucket, dict):
        return False
    return _ipr_key(card_id, comment_id) in bucket


def set_ipr_resolved(card_id, comment_id, *, by="manual"):
    if not card_id or not comment_id:
        return
    state = _load()
    bucket = state.setdefault("ipr_resolved", {})
    from datetime import timezone as _tz
    bucket[_ipr_key(card_id, comment_id)] = {
        "ts": datetime.now(_tz.utc).replace(tzinfo=None).isoformat(
            timespec="seconds"),
        "by": by,
    }
    _save(state)


def clear_ipr_resolved(card_id, comment_id):
    if not card_id or not comment_id:
        return
    state = _load()
    bucket = state.setdefault("ipr_resolved", {})
    bucket.pop(_ipr_key(card_id, comment_id), None)
    _save(state)


# ── Linked siblings — multi-unit commercial property groups ────────────────
# Each group is a named bundle of per-unit job folders that share a single
# physical property (e.g. "Highland Village Apartments" → ["Keystone-
# Highland Village (Unit 168)", "Keystone-Highland Village (Unit 170)", …]).
# Folders are stored as basenames (not absolute paths) so the link survives
# year-folder boundary changes; the audit base + year-folder walker re-
# resolves them at panel-render time.
#
# Schema:
#   property_groups: {
#       "<property name>": {
#           "folders": ["Keystone-Highland Village (Unit 168)", …],
#           "notes":   "<optional free-text>",
#           "created": "<iso timestamp>",
#       }, …
#   }

def get_property_groups():
    """Return the full {name: group_dict} map. Empty dict if none."""
    out = _load().get("property_groups", {})
    return out if isinstance(out, dict) else {}


def get_property_group(name):
    """Return one group's dict or None if it doesn't exist."""
    if not name:
        return None
    return get_property_groups().get(name)


def set_property_group(name, folders, *, notes=""):
    """Create or replace a property group. `folders` is a list of
    job-folder basenames; duplicates are deduped while preserving the
    caller's order so the panel renders units in a stable sequence."""
    if not name:
        return
    state = _load()
    groups = state.setdefault("property_groups", {})
    seen = set()
    unique_folders = []
    for f in folders or []:
        if not f:
            continue
        if f in seen:
            continue
        seen.add(f)
        unique_folders.append(f)
    existing = groups.get(name, {}) if isinstance(groups, dict) else {}
    from datetime import timezone as _tz
    groups[name] = {
        "folders": unique_folders,
        "notes":   notes or existing.get("notes", "") if isinstance(existing, dict) else (notes or ""),
        "created": (existing.get("created") if isinstance(existing, dict)
                    else None)
                   or datetime.now(_tz.utc).replace(tzinfo=None).isoformat(
                       timespec="seconds"),
    }
    _save(state)


def add_folder_to_property_group(name, folder):
    """Append one folder to an existing group (creates the group if
    missing). No-op if the folder is already in the list."""
    if not name or not folder:
        return
    g = get_property_group(name)
    folders = list(g.get("folders") or []) if isinstance(g, dict) else []
    if folder in folders:
        return
    folders.append(folder)
    set_property_group(name, folders,
                        notes=(g.get("notes") if isinstance(g, dict) else ""))


def remove_folder_from_property_group(name, folder):
    if not name or not folder:
        return
    g = get_property_group(name)
    if not isinstance(g, dict):
        return
    folders = [f for f in (g.get("folders") or []) if f != folder]
    set_property_group(name, folders, notes=g.get("notes", ""))


def delete_property_group(name):
    if not name:
        return
    state = _load()
    groups = state.setdefault("property_groups", {})
    if name in groups:
        del groups[name]
        _save(state)


def find_property_for_folder(folder):
    """Reverse lookup: which property group (if any) contains this
    folder. Returns the group name or None. Used by the audit row's
    right-click menu to surface the property association inline."""
    if not folder:
        return None
    for name, g in get_property_groups().items():
        if isinstance(g, dict) and folder in (g.get("folders") or []):
            return name
    return None


def clear_hygiene_scan_cache():
    set_value("hygiene_scan_cache", {})        # sidecar, not state.json


# ── Trello card warning dismissals (hygiene + handoff snoozing) ────────────
# Per-card, per-rule snooze: {card_id: {rule_id: iso_timestamp}}. The
# value is when the dismissal expires — past that, the warning re-surfaces
# in the next scan. Empty string means "permanent" (until the user clears).

def is_card_warning_dismissed(card_id, rule):
    """True when (card_id, rule) is currently snoozed. Permanent
    dismissals (empty timestamp) always return True; timed dismissals
    expire automatically without needing a sweep."""
    if not card_id or not rule:
        return False
    bucket = _load().get("dismissed_card_warnings", {}).get(card_id, {})
    if not isinstance(bucket, dict):
        return False
    until = bucket.get(rule)
    if until is None:
        return False
    if not until:
        return True   # permanent
    try:
        from datetime import timezone as _tz
        return (datetime.fromisoformat(until)
                > datetime.now(_tz.utc).replace(tzinfo=None))
    except (TypeError, ValueError):
        return False


def dismiss_card_warning(card_id, rule, *, hours=None):
    """Snooze (card_id, rule) for `hours` (None / 0 = permanent until
    cleared). Returns the iso-formatted expiry string written, or "" for
    permanent — useful for round-trip tests."""
    if not card_id or not rule:
        return ""
    state = _load()
    bucket = state.setdefault("dismissed_card_warnings", {})
    per_card = bucket.setdefault(card_id, {})
    if hours and hours > 0:
        # Naive UTC, kept consistent with isoformat parsing in is_card_warning_dismissed
        from datetime import timezone as _tz
        until = (datetime.now(_tz.utc).replace(tzinfo=None)
                 + _timedelta(hours=hours))
        per_card[rule] = until.isoformat(timespec="seconds")
    else:
        per_card[rule] = ""
    _save(state)
    return per_card[rule]


def clear_card_warning(card_id, rule=None):
    """Remove the snooze for (card_id, rule), or every snooze for the
    card when `rule` is None. Re-surfaces the warning on the next scan."""
    if not card_id:
        return
    state = _load()
    bucket = state.setdefault("dismissed_card_warnings", {})
    per_card = bucket.get(card_id, {})
    if not isinstance(per_card, dict):
        bucket.pop(card_id, None)
        _save(state)
        return
    if rule is None:
        bucket.pop(card_id, None)
    else:
        per_card.pop(rule, None)
        if not per_card:
            bucket.pop(card_id, None)
    _save(state)


def cleanup_stale_keys(audit_base, max_per_day=True):
    """Drop persistence entries for clients no longer found anywhere under
    audit_base. Conservative — only runs if the audit_base is reachable AND
    contains at least 100 client folders (sanity check against scanning
    a half-mounted share and nuking everything).

    Returns a {"removed": {...}} report so we can log how much was cleaned.
    """
    state = _load()
    if max_per_day:
        last = state.get("last_stale_cleanup", 0)
        if time.time() - float(last or 0) < 86400:
            return {"skipped": "ran in last 24h"}
    known = _all_known_clients(audit_base)
    if known is None or len(known) < 100:
        return {"skipped": "audit_base unreachable or suspiciously empty"}

    def _is_stale_client(key):
        # Match if any token of the key looks like a known client (substring
        # both ways for tolerance — clients have varying punctuation).
        k = " ".join(str(key).lower().split())
        if not k:
            return True
        for name in known:
            n = " ".join(name.split())
            if k in n or n in k:
                return False
        return True

    removed = {"folder_paths": [], "notes": []}

    # folder_paths is an EXPLICIT user override of the auto-resolver. The
    # whole point of pinning is that the client name on the job doesn't
    # match the folder on disk ("Anthony Sanchez" → "Antonio Sanchez"
    # folder). The previous _is_stale_client substring check considered
    # those overrides stale and deleted them — exactly the pins the user
    # needs most. Switched to a path-existence check: keep the pin as
    # long as the target folder is still reachable.
    fp = state.get("folder_paths", {})
    for k, v in list(fp.items()):
        keep = isinstance(v, str) and v and os.path.isdir(v)
        if not keep:
            removed["folder_paths"].append(k)
            del fp[k]

    notes = state.get("notes", {})
    for k in list(notes.keys()):
        if _is_stale_client(k):
            removed["notes"].append(k)
            del notes[k]

    # NOTE: apa_franchise_tags deliberately NOT swept here. Tags are
    # keyed by "client - carrier" (per apa_monitor_gui._franchise_key),
    # but the stale check matches against bare folder names like
    # "Smith, John". Year-suffixed folders ("Smith, John (2024)"),
    # commercial jobs filed under business name, or any client whose
    # folder spelling differs from the APA item text would all fail
    # the substring check and lose their franchise tag silently.
    # Tags are user-curated, low-volume, and a wrong-delete costs more
    # user time than keeping a stale tag. The user can clear individual
    # tags via the franchise picker UI if they want.

    state["last_stale_cleanup"] = time.time()
    _save(state)
    return {"removed": removed,
            "total": sum(len(v) for v in removed.values())}


# ── carrying local state across a merge ────────────────────────────────
#
# `merge_jobs` rewrites the shared database, but these caches live on THIS
# PC, keyed by client NAME. After a merge the loser's name is gone from
# the index while its cached folder path, Trello card ids and activity log
# sit here still answering to it — so a lookup by the old name gets a
# stale answer from a job that no longer exists.
#
# Stores keyed by a bare client name. Composite-key stores
# (`resolved_issues` = "date::client::issue", `apa_message_notes`,
# `audit_cache`) are deliberately NOT touched: rewriting half a compound
# key is how you turn stale data into wrong data.
_NAME_KEYED_STORES = (
    ("folder_paths", True),          # True = keyed by _canon_pin_key
    ("trello_card_ids", True),
    ("job_activity_log", False),
    ("apa_franchise_tags", False),
    ("apa_extended_history", False),
    ("sp_match_rejects", False),
    ("sp_match_overrides", False),
    ("commercial", False),
)


def rename_client(old_name, new_name):
    """Move this PC's cached state from `old_name` onto `new_name`.

    The survivor always wins a collision: it is the row the index kept,
    so its cached answers are the current ones. The loser's entry is
    dropped either way — leaving it behind is what strands it.

    Returns {store: action} for the caller to report. Never raises.
    """
    if not (old_name and new_name):
        return {}
    moved = {}
    try:
        state = _load()
    except Exception:
        return {}
    for store, canon in _NAME_KEYED_STORES:
        d = state.get(store)
        if not isinstance(d, dict):
            continue
        ok = _canon_pin_key(old_name) if canon else str(old_name).strip().lower()
        nk = _canon_pin_key(new_name) if canon else str(new_name).strip().lower()
        if not ok or ok == nk or ok not in d:
            continue
        val = d.pop(ok)
        if nk in d:
            moved[store] = "dropped (survivor already had one)"
        else:
            d[nk] = val
            moved[store] = "moved"
    if moved:
        try:
            _save(state)
        except Exception:
            return {}
    return moved
