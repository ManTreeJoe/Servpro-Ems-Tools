"""Pipeline stage classifier + sync.

Maps every Trello card to a lifecycle stage (New → Initial → Mitigation
→ Closeout → Estimating → Submitted → Approved → AR → Paid) using the
card's board + lane. The classifier is intentionally pattern-based so
it stays robust against lane rename / new-lane churn — substring rules
on board name + lane name beat a brittle id→stage table that goes
stale every time someone adds a new lane.

The Pipeline panel reads from ems_db.job_lifecycle which this module
populates via :func:`sync_workspace`. One pass walks every in-scope
board (the same list Hygiene uses). Each card upserts one lifecycle
row — ems_db handles the stage-transition timestamps.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable

import trello_client as tc
import ems_db


# Stage keys (ordered along the lifecycle). The Pipeline panel renders
# filter chips in this order; cycle-time metrics depend on the ordering
# too (a regression from a later stage back to earlier = anomaly).
STAGES = (
    "new",
    "initial",
    "mitigation",
    "closeout",
    "estimating",
    "submitted",
    "approved",
    "ar",
    "paid",
)

STAGE_LABELS = {
    "new":         "New",
    "initial":     "Initial Inspection",
    "mitigation":  "Mitigation",
    "closeout":    "Closeout",
    "estimating":  "Estimating",
    "submitted":   "Submitted",
    "approved":    "Approved",
    "ar":          "AR",
    "paid":        "Paid",
}

# Trello's detailed operational lanes project into a deliberately smaller
# master-job lifecycle. The original stage remains on job_lifecycle and on
# the EMS/Contents/Recon state; this mapping is only the cross-team summary.
CRM_STAGE_MAP = {
    "new": "intake",
    "initial": "contacted",
    "mitigation": "active",
    "closeout": "closeout",
    "estimating": "ready_for_billing",
    "submitted": "ready_for_billing",
    "approved": "ready_for_billing",
    "ar": "ready_for_billing",
    "paid": "closed",
}


def work_environment_for_board(board_name):
    """Which operational track owns a Trello card."""
    low = (board_name or "").lower()
    if "content" in low:
        return "Contents"
    if "recon" in low or "estimat" in low:
        return "Recon"
    return "EMS"


def crm_stage_for_pipeline(stage):
    return CRM_STAGE_MAP.get((stage or "").strip().lower(), "")


def reconcile_crm_lifecycle(rows=None):
    """Project Trello lifecycle rows onto the new master-job CRM safely.

    Department state always refreshes when a row resolves to a known job.
    Overall lifecycle updates only when every visible department agrees, and
    never overwrites a human-selected (`manual`) stage. Conflicting cards are
    returned as ambiguous for the future review queue instead of guessed.
    """
    if rows is None:
        rows = ems_db.lifecycle_list(paid_window_days=None)
    # Resolve the whole Trello projection against the job index in two bulk
    # reads. On Supabase, calling find_job_by_name for 3,000 lifecycle rows
    # means thousands of HTTP requests and makes reconciliation unusable.
    # Direct job keys win; ambiguous aliases are deliberately ignored.
    direct, aliases, alias_conflicts = {}, {}, set()
    try:
        for job in ems_db.iter_jobs() or []:
            key = job.get("canon_key") or ""
            if key:
                direct[key] = job
        for row in ems_db.all_aliases() or []:
            probe = ems_db.canon_key(row.get("alias") or "")
            key = row.get("canon_key") or ""
            if not probe or key not in direct:
                continue
            if probe in aliases and aliases[probe].get("canon_key") != key:
                alias_conflicts.add(probe)
            else:
                aliases[probe] = direct[key]
    except Exception:
        direct, aliases, alias_conflicts = {}, {}, set()

    grouped, unknown = {}, []
    for row in rows or []:
        name = (row.get("client_display") or "").strip()
        if not name:
            continue
        probe = ems_db.canon_key(name)
        job = direct.get(probe)
        if not job and probe not in alias_conflicts:
            job = aliases.get(probe)
        if not job and not direct:
            try:
                job = ems_db.find_job_by_name(name)
            except Exception:
                job = None
        if not job:
            unknown.append({"card_id": row.get("card_id") or "", "name": name})
            continue
        key = job.get("canon_key") or ""
        env = work_environment_for_board(row.get("board_name") or "")
        grouped.setdefault(key, {}).setdefault(env, []).append(row)

    updated_departments = updated_jobs = manual_preserved = 0
    ambiguous = []
    for key, environments in grouped.items():
        mapped = []
        for env, candidates in environments.items():
            # A job can have old duplicate cards. The newest activity is the
            # current operational signal; retain the rest in job_lifecycle.
            row = max(candidates, key=lambda r: (
                r.get("last_activity_at") or "", r.get("updated_at") or ""))
            stage = (row.get("current_stage") or "").strip().lower()
            try:
                ems_db.set_work_environment_state(
                    key, env, stage=stage, owner=row.get("owner") or "")
                updated_departments += 1
            except Exception:
                continue
            master_stage = crm_stage_for_pipeline(stage)
            if master_stage:
                mapped.append(master_stage)

        try:
            job = ems_db.get_job(key) or {}
        except Exception:
            job = {}
        if (job.get("lifecycle_source") or "").lower() == "manual":
            manual_preserved += 1
            continue
        distinct = sorted(set(mapped))
        if len(distinct) != 1:
            if distinct:
                ambiguous.append({"canon_key": key, "stages": distinct})
            continue
        try:
            ems_db.set_master_job_state(
                key, lifecycle_stage=distinct[0], source="trello")
            updated_jobs += 1
        except Exception:
            continue
    return {
        "jobs": len(grouped),
        "department_states": updated_departments,
        "master_stages": updated_jobs,
        "manual_preserved": manual_preserved,
        "ambiguous": ambiguous,
        "unknown": unknown,
    }

# Per-stage stall thresholds (business days). Surfaced in Hygiene
# Phase 2; KPI panel uses them to color-code rows + medians.
# `get_thresholds()` merges user overrides from persistence on top of
# these defaults — see the threshold-config dialog on the Pipeline
# panel for the live editor.
DEFAULT_STAGE_THRESHOLDS = {
    "new":         2,
    "initial":     3,
    "mitigation":  14,
    "closeout":    5,
    "estimating":  7,
    "submitted":   14,
    "approved":    5,
    "ar":          30,
    "paid":        9999,   # paid jobs are terminal; threshold = infinity
}

# Persistence key for the override dict. Stored as {stage_key: int_days}.
_THRESHOLDS_PER_KEY = "pipeline_stage_thresholds"


def get_thresholds():
    """Return the live thresholds dict: defaults overlaid with any
    user-set overrides from persistence. Read this anywhere the
    DEFAULT_STAGE_THRESHOLDS was previously used — keeps stale-detection
    + KPI coloring in sync with the threshold-config dialog."""
    try:
        import persistence as _per
        raw = _per.get(_THRESHOLDS_PER_KEY) or {}
    except Exception:
        raw = {}
    out = dict(DEFAULT_STAGE_THRESHOLDS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in DEFAULT_STAGE_THRESHOLDS:
                continue
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                continue
    return out


def set_threshold(stage, days):
    """Persist a per-stage threshold override. `days=None` clears the
    override and restores the default. No-op on unknown stage keys."""
    if stage not in DEFAULT_STAGE_THRESHOLDS:
        return
    try:
        import persistence as _per
        current = _per.get(_THRESHOLDS_PER_KEY) or {}
        if not isinstance(current, dict):
            current = {}
        if days is None:
            current.pop(stage, None)
        else:
            current[stage] = int(days)
        _per.set_value(_THRESHOLDS_PER_KEY, current)
    except Exception:
        pass


# Lanes that hold administrative / template / label / placeholder
# cards — anything matched here is excluded from the pipeline (and
# purged from job_lifecycle on the next sync). Case-insensitive
# substring match against the lane name.
_SKIP_LANE_SUBSTRINGS = (
    "template",        # 'Templates', 'Initial Inspection Template'
    "templet",         # misspelling caught in the wild
    "label",           # 'Labels', 'LABELS'
    "marketing team",  # admin team list
    "on call",         # 'ON CALL TEAMS'
    "collections process",
    "disposal",        # 'TOTAL IOSS DISPOSAL', 'GARMENTS RETURN'
    "garments",
)


# Card titles that are placeholder / reference cards even when they sit
# in an otherwise-real job lane. Matched as case-insensitive substrings
# (or exact-equal for very short titles to avoid false positives).
_SKIP_CARD_TITLE_SUBSTRINGS = (
    "template",
    "general info",
    "contact info",
    "collections process",
)

# Exact card-title matches (case-insensitive). Short titles like
# "Labels" / "Nichole" would over-match on substring search, so they
# only skip when the title is exactly one of these words.
_SKIP_CARD_TITLE_EXACT = {
    "labels",
    "label",
    "nichole",
}


def purge_skipped_lifecycle_rows() -> int:
    """One-shot — delete every job_lifecycle row whose (client_display,
    list_name) matches the skip filter. Run from PipelineApp._load so
    existing template/label/admin rows clean themselves up without
    waiting for the next full sync. Returns count deleted."""
    return ems_db.lifecycle_purge_where(
        lambda r: is_pipeline_skip(
            r.get("client_display") or "",
            r.get("list_name") or ""))


def is_pipeline_skip(card_name, lane_name):
    """True when the card is an administrative / template / label /
    placeholder card that doesn't belong in the pipeline view. Both
    lane name and card title are checked — covers cases like a
    'Labels' card in a real job lane and a 'General Info' card in a
    real customer lane."""
    lane_low = (lane_name or "").lower().strip()
    if lane_low and any(s in lane_low for s in _SKIP_LANE_SUBSTRINGS):
        return True
    title_low = (card_name or "").lower().strip()
    if not title_low:
        return False
    if title_low in _SKIP_CARD_TITLE_EXACT:
        return True
    if any(s in title_low for s in _SKIP_CARD_TITLE_SUBSTRINGS):
        return True
    return False


def _canon_name(s):
    """Match wc_audit._canon_name — lowercase + strip non-alnum so
    'KATHLEEN ACOSTA' matches 'Kathleen Acosta' / 'Smith,John' /
    'Smith, John' all resolve to the same key."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def derive_stage(board_name, list_name, *, closed=False):
    """Map (board_name, list_name) → stage key.

    Match priority:
      1. closed/archived card → 'paid' (the user's terminal state)
      2. AR board               → 'ar' or 'paid' (lane-dependent)
      3. PENDING APPROVAL lane  → 'submitted'
      4. APPROVED lane          → 'approved'
      5. Recon board            → 'mitigation'  (recon is in-progress work)
      6. Estimating board       → 'estimating'
      7. EMS / Contents board lane patterns:
            INBOX / NEW LOSS           → 'new'
            INITIAL / INSPECTION       → 'initial'
            SNAPSHOT / CLOSEOUT / READY → 'closeout'
            WORK / WIP / MITIGATION / MOLD / DEMO / DRYING / MONITOR → 'mitigation'
            (default for unmatched lane on these boards) → 'mitigation'
      8. Anything else            → 'mitigation' (conservative default —
                                    a job sitting on an unknown board is
                                    still in flight)
    """
    bl = (board_name or "").lower()
    ll = (list_name or "").lower()

    # 1. Closed/archived
    if closed:
        return "paid"

    # 2. AR board — billed or paid. Match "AR" as a whole word so we
    # don't catch "boARd" / "Recon BoARd" / similar substring traps.
    bl_tokens = bl.split()
    if ("ar" in bl_tokens or "billing" in bl
            or "accounts receivable" in bl):
        if "paid" in ll or "closed" in ll or "complete" in ll:
            return "paid"
        return "ar"

    # 3 + 4. Pending approval / approved lanes (any board)
    if "pending" in ll and "appr" in ll:
        return "submitted"
    if ll == "approved" or "approved" in ll.split():
        return "approved"

    # 5. Recon board
    if "recon" in bl:
        return "mitigation"

    # 6. Estimating board
    if "estimat" in bl:
        return "estimating"

    # 7. EMS / Contents / Monitor / Logs boards — lane pattern match
    if any(k in bl for k in ("ems", "contents", "monitor", "logs")):
        if any(k in ll for k in ("inbox", "new loss", "intake")):
            return "new"
        if any(k in ll for k in ("initial", "inspection")):
            return "initial"
        if any(k in ll for k in ("snapshot", "closeout", "close out",
                                  "ready for", "final")):
            return "closeout"
        if any(k in ll for k in ("wip", "work in progress", "mitigat",
                                  "mold", "demo", "drying", "monitor",
                                  "pack", "content")):
            return "mitigation"
        # Unmatched lane on an EMS-ish board — conservative: still
        # in-flight, so treat as mitigation.
        return "mitigation"

    # 8. Fallback for boards we don't have a rule for
    return "mitigation"


def days_in_stage(entry, *, today=None):
    """Days since `entry['stage_entered_at']`. Returns 0 when the
    timestamp is missing or unparseable (better than blowing up the
    panel render)."""
    s = (entry or {}).get("stage_entered_at") or ""
    if not s:
        return 0
    try:
        dt = _dt.datetime.fromisoformat(s.split("+")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return 0
    now = today or _dt.datetime.utcnow()
    return max(0, (now - dt).days)


def days_since_created(entry, *, today=None):
    """Days since the Trello card was created. Same fallback as above."""
    s = (entry or {}).get("created_at") or ""
    if not s:
        return 0
    try:
        dt = _dt.datetime.fromisoformat(s.split("+")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return 0
    now = today or _dt.datetime.utcnow()
    return max(0, (now - dt).days)


def is_stalled(entry, *, thresholds=None):
    """True when days_in_stage exceeds the configured threshold for
    the row's current_stage. Used for stall-coloring + Phase 2's
    Hygiene-section surfacing."""
    thresholds = thresholds or get_thresholds()
    stage = (entry or {}).get("current_stage") or ""
    th = thresholds.get(stage, 9999)
    return days_in_stage(entry) > th


# ── Sync ────────────────────────────────────────────────────────────────────


def sync_workspace(*, include_quality_boards=True, progress_cb=None):
    """One-pass scan that upserts a job_lifecycle row for every open
    card across all in-scope boards.

    `include_quality_boards=True` keeps AR/billing boards in scope so
    those cards stamp through to ar / paid stages. Set False to mirror
    Hygiene's filter (skip AR for hygiene-only context).

    `progress_cb(idx, total, board_name)` fires once per board so the
    Pipeline panel can paint a determinate progress bar during sync.

    Returns: {"boards": N, "cards": N, "stages": {stage_key: count}}.
    """
    boards = tc.list_boards(exclude_quality=not include_quality_boards) or []
    n_boards = len(boards)
    cards_total = 0
    stages_seen: dict[str, int] = {}
    synced_rows = []

    for bi, b in enumerate(boards, 1):
        if progress_cb is not None:
            try:
                progress_cb(bi, n_boards, b.get("name", ""))
            except Exception:
                pass
        try:
            lists = tc._call(
                f"/boards/{b['id']}/lists",
                params={"fields": "id,name", "filter": "open"},
            ) or []
        except Exception:
            continue
        for lst in lists:
            try:
                cards = tc.cards_in_list(
                    lst.get("id"),
                    fields=("id,name,shortUrl,idBoard,idList,closed,"
                            "idMembers,due,dateLastActivity")
                ) or []
            except Exception:
                continue
            for c in cards:
                name = (c.get("name") or "").strip()
                if not name:
                    continue
                # Filter out template / label / admin cards. If one
                # was previously inserted, delete its lifecycle row
                # so it stops showing in the Pipeline panel.
                if is_pipeline_skip(name, lst.get("name", "")):
                    try:
                        ems_db.lifecycle_delete(c["id"])
                    except Exception:
                        pass
                    continue
                stage = derive_stage(
                    b.get("name", ""),
                    lst.get("name", ""),
                    closed=bool(c.get("closed")))
                # For Estimating cards, lane name = owner (estimator).
                owner = (lst.get("name", "")
                          if stage == "estimating" else "")
                created_at = _card_created_iso(c.get("id", ""))
                lifecycle_row = {
                    "card_id":          c["id"],
                    "client_canon":     _canon_name(name),
                    "client_display":   name,
                    "board_id":         b.get("id", ""),
                    "board_name":       b.get("name", ""),
                    "list_id":          lst.get("id", ""),
                    "list_name":        lst.get("name", ""),
                    "current_stage":    stage,
                    "created_at":       created_at,
                    "last_activity_at": c.get("dateLastActivity") or "",
                    "card_url":         c.get("shortUrl", ""),
                    "owner":            owner,
                }
                ems_db.lifecycle_upsert(lifecycle_row)
                synced_rows.append(lifecycle_row)
                cards_total += 1
                stages_seen[stage] = stages_seen.get(stage, 0) + 1
    # Best-effort CRM projection. Pipeline sync remains useful on an older
    # database during a staggered rollout, so schema/API mismatch cannot make
    # the Trello scan itself fail.
    try:
        reconcile_crm_lifecycle(synced_rows)
    except Exception:
        pass
    return {
        "boards": n_boards,
        "cards":  cards_total,
        "stages": stages_seen,
    }


def _fetch_lane_entry_iso(card_id, target_list_id):
    """Return the ISO date when ``card_id`` most recently entered
    ``target_list_id`` (its current lane), or None when no usable
    action is found.

    Reads the card's actions log via ``/cards/{id}/actions`` with
    ``filter=updateCard,createCard``. updateCard actions whose
    ``data.old`` carries an ``idList`` key are lane moves; createCard
    actions cover the "card was made here and never moved" case.

    Trello returns actions newest-first, so the first hit is the
    most recent move INTO the current lane — exactly what we want.

    Network call. Phase 4 enrichment pass calls this once per
    lifecycle row that hasn't yet been enriched.
    """
    if not card_id or not target_list_id:
        return None
    try:
        actions = tc._call(
            f"/cards/{card_id}/actions",
            params={"filter": "updateCard,createCard", "limit": 50},
        ) or []
    except Exception:
        return None
    for a in actions:
        atype = a.get("type", "")
        data = a.get("data") or {}
        if atype == "updateCard":
            old = data.get("old") or {}
            if "idList" not in old:
                continue  # not a lane move (label/name/desc edit)
            # Trello returns the NEW idList in either listAfter
            # (newer responses) or card.idList (older). Try both.
            new_list_id = (
                (data.get("listAfter") or {}).get("id")
                or (data.get("card") or {}).get("idList"))
            if new_list_id == target_list_id:
                return a.get("date")
        elif atype == "createCard":
            created_list = (
                (data.get("list") or {}).get("id")
                or (data.get("card") or {}).get("idList"))
            if created_list == target_list_id:
                return a.get("date")
    return None


def enrich_stage_entered_from_actions(*, progress_cb=None, limit=None):
    """Walks lifecycle rows whose ``actions_synced_at`` is NULL, fetches
    each card's action log, and resets ``stage_entered_at`` to the
    exact lane-entry timestamp. Run after :func:`sync_workspace` — the
    fast main sync uses dateLastActivity as a proxy; this slow pass
    upgrades each row to honest Trello-derived dates.

    Idempotent: once a row is enriched (actions_synced_at stamped),
    it's never re-fetched UNLESS a stage transition clears that flag
    (see lifecycle_upsert).

    Cost: one Trello API call per un-enriched card. Wrap in a
    background thread; `progress_cb(i, total, card_id)` updates the
    UI per card.

    Returns: {"enriched": N, "no_data": N, "errors": N}.
    """
    needs = ems_db.lifecycle_needs_action_enrichment(limit=limit)
    total = len(needs)
    enriched = no_data = errors = 0
    for i, row in enumerate(needs, 1):
        if progress_cb is not None:
            try:
                progress_cb(i, total, row.get("card_id", ""))
            except Exception:
                pass
        cid = row.get("card_id")
        lid = row.get("list_id")
        if not cid or not lid:
            errors += 1
            continue
        try:
            iso = _fetch_lane_entry_iso(cid, lid)
        except Exception:
            errors += 1
            continue
        if iso:
            # Normalize to seconds-precision UTC matching the rest of
            # the table. Trello returns dates like
            # "2026-04-15T08:23:11.412Z" — strip the fractional + Z.
            iso_clean = iso.split(".")[0].rstrip("Z")
            ems_db.lifecycle_set_stage_entered(
                cid, stage_entered_at=iso_clean)
            enriched += 1
        else:
            # Mark synced anyway so we don't retry every sync. A
            # missing lane-move action means the card's actions log
            # didn't surface a usable date — usually a list rename or
            # API quirk; keeping the proxy stage_entered_at is fine.
            ems_db.lifecycle_mark_actions_synced(cid)
            no_data += 1
    return {"enriched": enriched, "no_data": no_data, "errors": errors}


def _card_created_iso(card_id):
    """Trello card IDs are 24-char hex strings whose first 8 hex digits
    encode the Unix timestamp. Cheap way to get card creation date
    without a per-card API call — saves a fetch per card during sync."""
    if not card_id or len(card_id) < 8:
        return ""
    try:
        ts = int(card_id[:8], 16)
    except ValueError:
        return ""
    return _dt.datetime.utcfromtimestamp(ts).replace(
        microsecond=0).isoformat()


def upsert_card(card, *, board_name=None, list_name=None):
    """Update a job_lifecycle row from a Trello card dict.

    Designed to piggyback on any existing scan loop that already has
    the card + board + lane in hand — costs one DB upsert per call,
    zero extra Trello API hits. Hygiene's workspace scan hooks this
    so every Trello fetch keeps the pipeline table fresh without
    the user having to click ↻ Sync.

    `board_name` / `list_name` can be passed explicitly OR pulled from
    `card["_board_name"]` / `card["_list_name"]` (the convention
    trello_hygiene._iter_all_cards stamps on every card it yields).
    """
    cid = (card or {}).get("id")
    if not cid:
        return
    name = (card.get("name") or "").strip()
    if not name:
        return
    bn = board_name if board_name is not None else card.get("_board_name", "")
    ln = list_name  if list_name  is not None else card.get("_list_name", "")
    # Skip template / label / admin cards — they don't represent real
    # jobs and were cluttering the Pipeline panel with multi-hundred-
    # day Mitigation rows. Belt-and-suspenders: also purges them from
    # the lifecycle table if they were inserted before this filter
    # existed, so the next sync cleans up legacy rows.
    if is_pipeline_skip(name, ln):
        try:
            ems_db.lifecycle_delete(cid)
        except Exception:
            pass
        return
    stage = derive_stage(bn, ln, closed=bool(card.get("closed")))
    owner = ln if stage == "estimating" else ""
    ems_db.lifecycle_upsert({
        "card_id":          cid,
        "client_canon":     _canon_name(name),
        "client_display":   name,
        "board_id":         card.get("idBoard", ""),
        "board_name":       bn,
        "list_id":          card.get("idList", ""),
        "list_name":        ln,
        "current_stage":    stage,
        "created_at":       _card_created_iso(cid),
        "last_activity_at": card.get("dateLastActivity") or "",
        "card_url":         card.get("shortUrl", ""),
        "owner":            owner,
    })


def list_stalled(*, thresholds=None, paid_window_days=30):
    """Return every active lifecycle row where days_in_stage exceeds
    the per-stage threshold. Surfaced by Hygiene as a stand-alone
    section. Sorted longest-stall first."""
    thresholds = thresholds or get_thresholds()
    rows = ems_db.lifecycle_list(paid_window_days=paid_window_days)
    out = []
    for r in rows:
        stage = (r.get("current_stage") or "")
        if stage == "paid":
            continue  # paid is terminal, never "stalled"
        d = days_in_stage(r)
        th = thresholds.get(stage, 9999)
        if d > th:
            out.append({**r,
                        "_days_in_stage":  d,
                        "_stage_threshold": th})
    out.sort(key=lambda r: -(r.get("_days_in_stage") or 0))
    return out


def historical_stage_stats(*, lookback_days=180):
    """Per-stage cycle time computed from COMPLETED transitions over
    the last `lookback_days`. Each completed exit from a stage gives
    one sample of how long that stage actually took (vs the
    current-state median, which only sees today's active backlog).

    Returns {stage_key: {sample_size, median, p90, max}}.
    Stages with no completed exits in the window get zeros.
    """
    since = (_dt.datetime.utcnow()
              - _dt.timedelta(days=lookback_days)).isoformat()
    transitions = ems_db.list_transitions(since_iso=since)
    by_stage: dict[str, list[int]] = {s: [] for s in STAGES}
    for t in transitions:
        s = t.get("from_stage") or ""
        if s not in by_stage:
            continue
        d = t.get("days_in_from_stage")
        if d is None:
            continue
        by_stage[s].append(int(d))

    def _pct(values, p):
        if not values:
            return 0
        sorted_v = sorted(values)
        idx = max(0, min(len(sorted_v) - 1,
                         int(round((p / 100.0) * len(sorted_v))) - 1))
        return sorted_v[idx]

    out = {}
    for stage, vals in by_stage.items():
        out[stage] = {
            "sample_size": len(vals),
            "median":      _pct(vals, 50),
            "p90":         _pct(vals, 90),
            "max":         max(vals) if vals else 0,
        }
    return out


def is_anomaly(entry, *, history=None, multiplier=3, min_sample=5,
                 min_abs_days=7):
    """True when a row's days_in_stage is at least `multiplier` × the
    historical median for that stage AND we have enough historical
    samples to trust the comparison AND the absolute days_in_stage is
    above the noise floor (≥ min_abs_days).

    Distinct from `is_stalled` (which uses static thresholds): anomaly
    is "this job is much slower than the norm FOR THIS STAGE", where
    a stage that's systemically slow doesn't trigger anomalies on
    every row. A job can be both stalled AND anomalous (slow vs the
    threshold and ALSO slow vs its own stage's history).

    `min_abs_days` (default 7) prevents trivial fires: when the
    historical median is 1d (small sample, all quick moves), 3×
    would call a 3-day stay "anomalous" — but anything under a work
    week is just normal-stage churn, not worth surfacing."""
    stage = (entry or {}).get("current_stage") or ""
    if stage == "paid":
        return False
    if history is None:
        history = historical_stage_stats()
    s = history.get(stage) or {}
    if s.get("sample_size", 0) < min_sample:
        return False
    med = s.get("median") or 0
    if med <= 0:
        return False
    d = days_in_stage(entry)
    if d < min_abs_days:
        return False
    return d > med * multiplier


def list_anomalies(*, multiplier=3, min_sample=5, min_abs_days=7,
                    paid_window_days=30):
    """Active lifecycle rows whose days_in_stage exceeds
    `multiplier` × the historical median for their stage AND is past
    the absolute noise floor. Sorted by excess ratio (most-extreme
    first) so the worst outliers surface at the top. Each row carries
    `_anomaly_ratio` (days_in / hist_med) + `_hist_median` for the
    UI to display."""
    history = historical_stage_stats()
    rows = ems_db.lifecycle_list(paid_window_days=paid_window_days)
    out = []
    for r in rows:
        stage = (r.get("current_stage") or "")
        if stage == "paid":
            continue
        s = history.get(stage) or {}
        if s.get("sample_size", 0) < min_sample:
            continue
        med = s.get("median") or 0
        if med <= 0:
            continue
        d = days_in_stage(r)
        if d < min_abs_days:
            continue
        if d <= med * multiplier:
            continue
        out.append({**r,
                    "_days_in_stage": d,
                    "_hist_median":   med,
                    "_anomaly_ratio": (d / med) if med else 0.0})
    out.sort(key=lambda r: -(r.get("_anomaly_ratio") or 0))
    return out


def stage_cycle_stats(*, paid_window_days=90):
    """Per-stage median + p90 days-in-current-stage, plus count.

    Phase 2 metric — surfaces "where are jobs piling up" without
    needing full transition history (which lives in Phase 3). Returns:
        {stage_key: {count, median, p90, max}}
    Empty buckets get a row too so the KPI panel can render zeros.
    """
    rows = ems_db.lifecycle_list(paid_window_days=paid_window_days)
    by_stage: dict[str, list[int]] = {s: [] for s in STAGES}
    for r in rows:
        stage = r.get("current_stage") or ""
        if stage not in by_stage:
            continue
        by_stage[stage].append(days_in_stage(r))

    def _pct(values, p):
        if not values:
            return 0
        s = sorted(values)
        # Nearest-rank percentile — exact enough for an ops dashboard
        # and avoids the numpy/statistics fp-edge cases on tiny lists.
        idx = max(0, min(len(s) - 1,
                         int(round((p / 100.0) * len(s))) - 1))
        return s[idx]

    out = {}
    for stage, vals in by_stage.items():
        out[stage] = {
            "count":  len(vals),
            "median": _pct(vals, 50),
            "p90":    _pct(vals, 90),
            "max":    max(vals) if vals else 0,
        }
    return out
