"""Safe user-facing job merge/delete operations for every web panel."""
from __future__ import annotations


_CARRY_FIELDS = (
    "carrier", "claim_number", "address", "phone", "email",
    "adjuster_name", "adjuster_email", "adjuster_phone", "date_of_loss",
    "loss_type", "xa_id", "wc_project_id",
)


def _job(ref):
    import ems_db
    ref = (ref or "").strip()
    return ems_db.get_job(ref) or ems_db.find_job_by_name(ref)


def _summary(row):
    if not row:
        return {}
    return {k: row.get(k) or "" for k in (
        "canon_key", "display_name", "department", "carrier",
        "claim_number", "address", "last_seen_at")}


class JobAdminApi:
    """Mixin: read-first plans plus guarded destructive commits."""

    def job_admin_suggest(self, query: str, exclude_key: str = "",
                          limit: int = 8) -> dict:
        try:
            import job_search
            rows = [r for r in job_search.suggest(query, int(limit or 8) + 4)
                    if not r.get("child_name")
                    and r.get("canon_key") != (exclude_key or "").strip()]
            return {"ok": True, "rows": rows[:int(limit or 8)]}
        except Exception as ex:
            return {"ok": False, "rows": [],
                    "error": f"{type(ex).__name__}: {ex}"}

    def job_delete_preview(self, job_ref: str) -> dict:
        try:
            import ems_db
            row = _job(job_ref)
            if not row:
                return {"ok": False, "error": "Job not found"}
            key = row["canon_key"]
            aliases = list(ems_db.get_aliases(key) or [])
            links = list(ems_db.get_links(key) or [])
            children = list(ems_db.children_of(key) or [])
            return {"ok": True, "job": _summary(row),
                    "aliases": aliases,
                    "links": [{"type": l.get("link_type") or "",
                               "value": l.get("link_value") or ""}
                              for l in links],
                    "children": [c.get("name") or "" for c in children],
                    "external_untouched": True}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def job_delete_apply(self, canon_key: str,
                         confirm_name: str) -> dict:
        try:
            import ems_db
            row = ems_db.get_job((canon_key or "").strip())
            if not row:
                return {"ok": False, "error": "Job is already gone"}
            name = (row.get("display_name") or "").strip()
            if (confirm_name or "").strip() != name:
                return {"ok": False,
                        "error": "Type the full job name exactly to delete it"}
            res = ems_db.delete_job(
                row["canon_key"], note=f"deleted from Job management: {name}")
            if not res.get("deleted"):
                return {"ok": False, "error": "Job was not deleted"}
            try:
                import job_search
                job_search.invalidate_cache()
            except Exception:
                pass
            return {"ok": True, **res, "external_untouched": True}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def job_merge_preview(self, keep_ref: str, drop_ref: str) -> dict:
        try:
            import ems_db
            keep, drop = _job(keep_ref), _job(drop_ref)
            if not keep or not drop:
                return {"ok": False, "error": "Both jobs must exist"}
            if keep["canon_key"] == drop["canon_key"]:
                return {"ok": False, "error": "Choose two different jobs"}
            preview = ems_db.merge_preview(
                keep["canon_key"], [drop["canon_key"]])
            carried = [f for f in _CARRY_FIELDS
                       if not (keep.get(f) or "").strip()
                       and (drop.get(f) or "").strip()]
            conflicts = [f for f in _CARRY_FIELDS
                         if (keep.get(f) or "").strip()
                         and (drop.get(f) or "").strip()
                         and str(keep[f]).strip().casefold()
                         != str(drop[f]).strip().casefold()]
            return {"ok": True, "keep": _summary(keep),
                    "drop": _summary(drop), "preview": preview,
                    "carried": carried, "conflicts": conflicts}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def job_merge_apply(self, keep_key: str, drop_key: str,
                        confirm_drop_name: str) -> dict:
        try:
            import ems_db
            keep = ems_db.get_job((keep_key or "").strip())
            drop = ems_db.get_job((drop_key or "").strip())
            if not keep or not drop:
                return {"ok": False, "error": "One of the jobs is gone"}
            if keep["canon_key"] == drop["canon_key"]:
                return {"ok": False, "error": "Choose two different jobs"}
            drop_name = (drop.get("display_name") or "").strip()
            if (confirm_drop_name or "").strip() != drop_name:
                return {"ok": False,
                        "error": "The folded job name did not match"}
            pv = ems_db.merge_preview(keep["canon_key"], [drop["canon_key"]])
            if pv.get("department_conflicts"):
                return {"ok": False,
                        "error": "Jobs from different departments cannot be merged"}
            carried = {}
            for field in _CARRY_FIELDS:
                if not (keep.get(field) or "").strip() and \
                        (drop.get(field) or "").strip():
                    carried[field] = drop[field]
            if carried:
                ems_db.upsert_job(
                    display_name=keep.get("display_name") or keep["canon_key"],
                    **carried)
            res = ems_db.merge_jobs(
                keep["canon_key"], [drop["canon_key"]],
                note=f"merged {drop_name} into {keep.get('display_name')}")
            if not res.get("merged"):
                return {"ok": False, "error": "Jobs were not merged",
                        "skipped": res.get("skipped_department_conflict") or []}
            try:
                import job_search
                job_search.invalidate_cache()
            except Exception:
                pass
            return {"ok": True, **res, "carried": sorted(carried),
                    "keep_name": keep.get("display_name") or keep["canon_key"]}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
