"""KPI metrics — pure data extraction from existing telemetry.

The role doc lists "KPI performance for all EMS roles" as a Leadership
Oversight item. This module pulls weekly-rolled metrics from every
data source the suite already populates, so the KPI panel can render
a snapshot + trend without any new collection layer.

Data sources (read-only):
    audit_export.load_audit_backlog()       — per-job audit history
    persistence.get("resolved_issues")      — per-day flag resolutions
    persistence.get("escalations_sent")     — 🚩 button activity
    persistence.get("ar_xa_handled")        — Tier 2-G XA apologies
    persistence.get("adjuster_receipt_posted") — Tier 2-F inbound receipts
    persistence.get("closeout_drafted")     — Tier 1-C snapshot drafts
    persistence.get_hygiene_scan_cache()    — current open-flag counts

Output shape (`weekly_metrics`):
    [
      {
        "week_start": "2026-05-04",   # Monday ISO
        "audits_run": 12,             # jobs touched this week
        "flagged":    3,              # of those, FLAG count
        "resolved":   7,              # checkbox flips this week
        "escalations": 1,             # 🚩 button clicks
        "xa_apologies": 4,            # AR/XA apology marks
        "snapshots_drafted": 2,       # closeout_drafted entries
        "adjuster_receipts": 0,       # email-routed receipts
      },
      ...
    ]

Returned newest-first, capped at `weeks_back` entries.
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any

import audit_export
import persistence as per


# ── Week-bucket helpers ────────────────────────────────────────────────────

def _monday(d: _dt.date | None = None) -> _dt.date:
    d = d or _dt.date.today()
    return d - _dt.timedelta(days=d.weekday())


def _week_str(d: _dt.date) -> str:
    return _monday(d).isoformat()


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _parse_date_part(s: str) -> _dt.date | None:
    """Many keys in persistence are formatted MM-DD-YYYY (audit run-date
    convention). Parse those AND ISO dates equally so this module
    doesn't care which format the source used."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return _dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _week_buckets(weeks_back: int) -> list[str]:
    """Return week-start ISO strings, newest first, length `weeks_back`."""
    today = _dt.date.today()
    return [_week_str(today - _dt.timedelta(weeks=i))
            for i in range(weeks_back)]


# ── Per-source extractors ──────────────────────────────────────────────────

def _audit_metrics_per_week(weeks: list[str]) -> dict[str, dict]:
    """{week_start: {audits_run, flagged}} aggregated from audit_backlog.
    Each backlog entry's `week_start` field tells us which week it was
    last audited in; entries audited multiple times this week still
    count once (the audit_count tracks repeats but our weekly metric
    is unique-jobs-touched)."""
    out: dict[str, dict] = {w: {"audits_run": 0, "flagged": 0} for w in weeks}
    try:
        data = audit_export.load_audit_backlog()
    except Exception:
        return out
    for j in data.get("jobs", []):
        ws = (j.get("week_start") or "").strip()
        if ws not in out:
            continue
        out[ws]["audits_run"] += 1
        if (j.get("status") or "").upper() == "FLAG":
            out[ws]["flagged"] += 1
    return out


def _resolved_per_week(weeks: list[str]) -> dict[str, int]:
    """Count of resolved-issue checkbox flips per week. Keys in
    persistence's `resolved_issues` look like
    `MM-DD-YYYY::client::issue` → True. We bucket by the run_date
    portion."""
    out = {w: 0 for w in weeks}
    bucket = per.get("resolved_issues") or {}
    if not isinstance(bucket, dict):
        return out
    for key in bucket.keys():
        date_part = key.split("::", 1)[0] if "::" in key else ""
        d = _parse_date_part(date_part)
        if d is None:
            continue
        ws = _week_str(d)
        if ws in out:
            out[ws] += 1
    return out


def _escalations_per_week(weeks: list[str]) -> dict[str, int]:
    """Count of 🚩 escalation-message-sent events per week. Keys look
    like `MM-DD-YYYY::client` → unix timestamp."""
    out = {w: 0 for w in weeks}
    bucket = per.get("escalations_sent") or {}
    if not isinstance(bucket, dict):
        return out
    for key in bucket.keys():
        date_part = key.split("::", 1)[0] if "::" in key else ""
        d = _parse_date_part(date_part)
        if d is None:
            continue
        ws = _week_str(d)
        if ws in out:
            out[ws] += 1
    return out


def _iso_value_per_week(weeks: list[str], data: dict | None) -> dict[str, int]:
    """Generic extractor for {card_id: iso_timestamp} maps. Buckets the
    ISO value's date into a week."""
    out = {w: 0 for w in weeks}
    if not isinstance(data, dict):
        return out
    for v in data.values():
        if isinstance(v, list):
            # adjuster_receipt_posted is {card_id: [msg_ids]} — a list
            # length proxies "comments posted to that card", which is
            # exactly what we want to count, but each list is the FULL
            # history for that card. Without per-msg timestamps we
            # can't bucket precisely, so attribute every entry to the
            # current week as a coarse approximation. The metric is
            # primarily used for "is anything happening" trend lines,
            # not legal-grade auditing.
            ws = weeks[0] if weeks else ""
            if ws:
                out[ws] += len(v)
            continue
        dt = _parse_iso(str(v))
        if dt is None:
            continue
        ws = _week_str(dt.date())
        if ws in out:
            out[ws] += 1
    return out


# ── Public aggregator ──────────────────────────────────────────────────────

def weekly_metrics(*, weeks_back: int = 4) -> list[dict[str, Any]]:
    """Roll up the last `weeks_back` weeks (newest first). Defaults to
    4 — enough for a "current vs prior 3 weeks" trend without burning
    panel space. Always returns exactly `weeks_back` entries; weeks
    with no activity show zeros so the trend renderer doesn't have to
    handle gaps."""
    weeks = _week_buckets(weeks_back)
    audits = _audit_metrics_per_week(weeks)
    resolved = _resolved_per_week(weeks)
    escal = _escalations_per_week(weeks)
    xa = _iso_value_per_week(weeks, per.get("ar_xa_handled"))
    snaps = _iso_value_per_week(weeks, per.get("closeout_drafted"))
    adj = _iso_value_per_week(weeks, per.get("adjuster_receipt_posted"))
    out: list[dict[str, Any]] = []
    for w in weeks:
        out.append({
            "week_start":         w,
            "audits_run":         audits[w]["audits_run"],
            "flagged":            audits[w]["flagged"],
            "resolved":           resolved.get(w, 0),
            "escalations":        escal.get(w, 0),
            "xa_apologies":       xa.get(w, 0),
            "snapshots_drafted":  snaps.get(w, 0),
            "adjuster_receipts":  adj.get(w, 0),
        })
    return out


def current_open_flags() -> dict[str, int]:
    """Snapshot counts from the most recent hygiene scan cache —
    'right now' state, not a weekly aggregate. Returns zeros across
    the board when the panel hasn't run yet (so the GUI can render
    cleanly without special-casing missing data)."""
    out = {"concerns": 0, "xa_apology": 0, "hygiene": 0,
           "handoff": 0, "closeout": 0, "scanned": False}
    cache = per.get_hygiene_scan_cache(max_age_minutes=24 * 60)
    if cache is None:
        return out
    payload, _age = cache
    out["scanned"] = True
    hyg = payload.get("hygiene") or []
    out["concerns"] = sum(1 for v in hyg
                          if v.get("rule") == "customer_complaint")
    out["handoff"]  = sum(1 for v in hyg
                          if v.get("rule") == "lane_move_no_handoff")
    out["hygiene"]  = sum(1 for v in hyg
                          if v.get("rule") not in
                          ("customer_complaint", "lane_move_no_handoff"))
    out["xa_apology"] = len(payload.get("xa_apology") or [])
    out["closeout"] = len(payload.get("closeout") or [])
    return out


def cycle_time_stats(*, longest_n: int = 5) -> dict[str, Any]:
    """Job cycle-time aggregates derived from ems_db `first_seen_at`
    timestamps + `closeout_drafted` close signals. A job is "closed"
    when ANY of its pinned Trello card IDs appears in the
    `closeout_drafted` map; otherwise it counts as still open and
    its days-open is measured against today.

    Returns::

        {
          "open_count":             int,
          "closed_count":           int,
          "avg_days_open":          float | None,
          "median_days_open":       float | None,
          "p90_days_open":          float | None,
          "avg_days_to_close":      float | None,
          "median_days_to_close":   float | None,
          "longest_open": [{"client", "days"}, ...],   # top N
        }

    All values are None when the underlying lists are empty so the
    GUI can render "no data" without dividing by zero.
    """
    out: dict[str, Any] = {
        "open_count": 0,
        "closed_count": 0,
        "avg_days_open": None,
        "median_days_open": None,
        "p90_days_open": None,
        "avg_days_to_close": None,
        "median_days_to_close": None,
        "longest_open": [],
    }
    try:
        import ems_db
        jobs = ems_db.iter_jobs()
    except Exception:
        return out
    closeout_map = per.get("closeout_drafted") or {}
    if not isinstance(closeout_map, dict):
        closeout_map = {}
    now = _dt.datetime.now()

    # Backfill: ems_db.first_seen_at is when the local DB started
    # tracking a job — typically much later than the job's real
    # intake date. For each client, also surface the earliest audit
    # week_start from audit_backlog and pick the earlier of the two
    # as the start signal. This lets cycle-time reflect history that
    # predates the db rollout.
    earliest_audit_by_client: dict[str, _dt.date] = {}
    try:
        for ab in audit_export.load_audit_backlog().get("jobs", []):
            ws = _parse_date_part(ab.get("week_start") or "")
            cname = (ab.get("client") or "").strip()
            if not cname or ws is None:
                continue
            prev = earliest_audit_by_client.get(cname)
            if prev is None or ws < prev:
                earliest_audit_by_client[cname] = ws
    except Exception:
        pass

    days_open: list[float] = []
    days_closed: list[float] = []
    open_pairs: list[tuple[str, float]] = []   # (client, days)
    for j in jobs:
        first_seen = _parse_iso(j.get("first_seen_at") or "")
        client = j.get("display_name") or ""
        # Augment with earliest known audit date for this client.
        audit_start_d = earliest_audit_by_client.get(client)
        if audit_start_d is not None:
            audit_start = _dt.datetime.combine(audit_start_d, _dt.time())
            if first_seen is None or audit_start < first_seen:
                first_seen = audit_start
        if first_seen is None:
            continue
        # Card-id bridge into closeout_drafted. Pulls from persistence
        # rather than ems_db.job_links so the canonicalization layer
        # already in place for trello pins (see _canon_pin_key) does
        # the lookup for us.
        try:
            card_ids = per.get_trello_card_ids(client) or []
        except Exception:
            card_ids = []
        closeout_iso = None
        for cid in card_ids:
            if cid in closeout_map:
                closeout_iso = closeout_map[cid]
                break
        if closeout_iso:
            close_dt = _parse_iso(str(closeout_iso))
            if close_dt is None or close_dt < first_seen:
                continue
            d = (close_dt - first_seen).total_seconds() / 86400.0
            days_closed.append(d)
            out["closed_count"] += 1
        else:
            d = (now - first_seen).total_seconds() / 86400.0
            if d < 0:
                continue
            days_open.append(d)
            open_pairs.append((client, d))
            out["open_count"] += 1

    def _avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    def _median(xs):
        if not xs:
            return None
        s = sorted(xs)
        n = len(s)
        return round((s[n // 2] if n % 2
                      else (s[n // 2 - 1] + s[n // 2]) / 2.0), 1)

    def _p90(xs):
        if not xs:
            return None
        s = sorted(xs)
        # Nearest-rank method — fine for small N (this dataset).
        idx = max(0, int(round(0.9 * len(s))) - 1)
        return round(s[idx], 1)

    out["avg_days_open"] = _avg(days_open)
    out["median_days_open"] = _median(days_open)
    out["p90_days_open"] = _p90(days_open)
    out["avg_days_to_close"] = _avg(days_closed)
    out["median_days_to_close"] = _median(days_closed)
    open_pairs.sort(key=lambda p: p[1], reverse=True)
    out["longest_open"] = [
        {"client": c, "days": round(d, 1)}
        for c, d in open_pairs[:longest_n]
    ]
    return out


def repeat_offenders(*, threshold: int = 5,
                      limit: int = 10) -> list[dict[str, Any]]:
    """Jobs flagged on `threshold` or more audits — the chronic
    problem cases. Returned newest-audit first so a job that hit the
    threshold long ago and went quiet doesn't push fresh repeat
    offenders off the top."""
    try:
        data = audit_export.load_audit_backlog()
    except Exception:
        return []
    out = [j for j in data.get("jobs", [])
           if (j.get("audit_count") or 0) >= threshold
           and (j.get("status") or "").upper() == "FLAG"]
    out.sort(key=lambda j: j.get("last_audited", ""), reverse=True)
    return out[:limit]


def _operational_group_rollup(lifecycle, transitions) -> dict[str, Any]:
    """Project the existing stage history through the shared group clocks."""
    try:
        import operational_tracking as tracking
        import pipeline_stages
    except Exception:
        return {"groups": [], "jobs": 0, "clock_quality": "unavailable"}
    by_card = defaultdict(list)
    for row in transitions or []:
        card_id = str(row.get("card_id") or "")
        if card_id:
            by_card[card_id].append(row)
    thresholds = pipeline_stages.get_thresholds()
    projected = [
        tracking.project_stage_history(
            by_card.get(str(row.get("card_id") or ""), []),
            row, thresholds=thresholds)
        for row in (lifecycle or []) if row.get("card_id")
    ]
    result = tracking.rollup(projected)
    result["clock_quality"] = "estimated_from_stage_history"
    result["note"] = (
        "Existing history has total stage time. Controllable time becomes exact "
        "as approved pause and handoff events are recorded in Linguar Hub."
    )
    return result


def operational_group_stats(*, days_back: int = 90) -> dict[str, Any]:
    """Front Operations, Field, and Estimating cycle-time rollup."""
    try:
        import ems_db
        since = (_dt.datetime.now() - _dt.timedelta(days=days_back)).isoformat()
        transitions = ems_db.list_transitions(since_iso=since, limit=5000)
        lifecycle = ems_db.lifecycle_list(paid_window_days=None)
    except Exception:
        return {"groups": [], "jobs": 0, "clock_quality": "unavailable"}
    return _operational_group_rollup(lifecycle, transitions)


def job_performance_stats(*, days_back: int = 90) -> dict[str, Any]:
    """Stage bottlenecks, current stalls, and monthly completion progress."""
    out = {"stage_bottlenecks": [], "stalled_jobs": [],
           "operational_groups": {"groups": [], "jobs": 0,
                                  "clock_quality": "unavailable"},
           "completed_this_month": 0, "monthly_quota": 0,
           "quota_remaining": 0, "quota_percent": None}
    try:
        import ems_db
        jobs = ems_db.iter_jobs()
        since = (_dt.datetime.now() - _dt.timedelta(days=days_back)).isoformat()
        transitions = ems_db.list_transitions(since_iso=since, limit=5000)
        lifecycle = ems_db.lifecycle_list(paid_window_days=None)
    except Exception:
        return out

    out["operational_groups"] = _operational_group_rollup(
        lifecycle, transitions)

    by_stage: dict[str, list[float]] = {}
    for row in transitions:
        stage = str(row.get("from_stage") or "").strip()
        try:
            days = float(row.get("days_in_from_stage"))
        except (TypeError, ValueError):
            continue
        if stage and days >= 0:
            by_stage.setdefault(stage, []).append(days)
    for stage, values in by_stage.items():
        values.sort()
        n = len(values)
        median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        out["stage_bottlenecks"].append({
            "stage": stage, "exits": n,
            "avg_days": round(sum(values) / n, 1),
            "median_days": round(median, 1),
            "p90_days": round(values[max(0, int(round(.9 * n)) - 1)], 1),
        })
    out["stage_bottlenecks"].sort(key=lambda x: (x["avg_days"], x["exits"]), reverse=True)

    now = _dt.datetime.now()
    for row in lifecycle:
        entered = _parse_iso(row.get("stage_entered_at") or "")
        if not entered or (row.get("current_stage") or "").lower() == "paid":
            continue
        days = max(0, (now - entered).total_seconds() / 86400)
        if days >= 3:
            out["stalled_jobs"].append({
                "client": row.get("client_display") or row.get("client_canon") or "?",
                "stage": row.get("current_stage") or "unknown",
                "days": round(days, 1), "owner": row.get("owner") or "",
            })
    out["stalled_jobs"].sort(key=lambda x: x["days"], reverse=True)
    out["stalled_jobs"] = out["stalled_jobs"][:10]

    month_prefix = now.strftime("%Y-%m")
    out["completed_this_month"] = sum(
        1 for job in jobs if str(job.get("closed_at") or "").startswith(month_prefix))
    try:
        import config
        quota = int((config.load() or {}).get("monthly_job_completion_quota") or 0)
    except (TypeError, ValueError):
        quota = 0
    out["monthly_quota"] = max(0, quota)
    if quota > 0:
        out["quota_remaining"] = max(0, quota - out["completed_this_month"])
        out["quota_percent"] = round(100 * out["completed_this_month"] / quota)
    return out


# ── CLI smoke test ─────────────────────────────────────────────────────────

def _cli(argv):
    if not argv or argv[0] == "weekly":
        weeks = 4
        for a in argv[1:]:
            if a.startswith("--weeks="):
                try: weeks = int(a.split("=", 1)[1])
                except ValueError: pass
        rows = weekly_metrics(weeks_back=weeks)
        head = ("week", "aud", "flg", "res", "esc",
                "xa", "snp", "adj")
        widths = (12, 4, 4, 4, 4, 4, 4, 4)
        print(" ".join(h.ljust(w) for h, w in zip(head, widths)))
        for r in rows:
            row = (r["week_start"],
                   str(r["audits_run"]), str(r["flagged"]),
                   str(r["resolved"]), str(r["escalations"]),
                   str(r["xa_apologies"]), str(r["snapshots_drafted"]),
                   str(r["adjuster_receipts"]))
            print(" ".join(c.ljust(w) for c, w in zip(row, widths)))
        return 0
    if argv[0] == "open":
        snap = current_open_flags()
        print(snap)
        return 0
    if argv[0] == "repeat":
        for j in repeat_offenders():
            print(f"  {j.get('client', '?')}  ×{j.get('audit_count', 0)}  "
                  f"last {j.get('last_audited', '')[:10]}")
        return 0
    if argv[0] == "cycle":
        s = cycle_time_stats()
        print(f"open jobs:   {s['open_count']}")
        print(f"closed jobs: {s['closed_count']}")
        def _fmt(v):
            return "—" if v is None else f"{v} d"
        print(f"open: avg {_fmt(s['avg_days_open'])} · "
              f"med {_fmt(s['median_days_open'])} · "
              f"p90 {_fmt(s['p90_days_open'])}")
        print(f"close: avg {_fmt(s['avg_days_to_close'])} · "
              f"med {_fmt(s['median_days_to_close'])}")
        if s["longest_open"]:
            print("longest open:")
            for row in s["longest_open"]:
                print(f"  {row['days']:>5} d  {row['client']}")
        return 0
    print("Usage: kpi_metrics.py weekly [--weeks=N] | open | repeat | cycle")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
