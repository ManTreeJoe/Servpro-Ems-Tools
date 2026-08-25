"""Consolidated Exceptions panel.

This is a read-only triage surface over the existing Hygiene cache,
identity checks, and Data & Sync Health.  It deliberately does not run a
second scan or maintain a second issue database.
"""
from __future__ import annotations

import os

import paths
import persistence
import hygiene_web

INDEX_HTML = os.path.join(paths.RESOURCE_DIR, "exceptions_web_assets", "index.html")


class Api:
    def __init__(self):
        self._window = None
        self._hygiene = hygiene_web.Api()

    def attach(self, window):
        self._window = window
        self._hygiene.attach(window)

    def summary(self, force=False):
        cache = self._hygiene.get_cache()
        by_key = {s["key"]: s for s in cache.get("sections", [])}
        categories = []
        for display in cache.get("display", []):
            count = sum(int(by_key.get(k, {}).get("count") or 0)
                        for k in display.get("keys", []))
            if count or display.get("feed") is not False:
                categories.append({
                    "key": display["key"],
                    "label": display["label"],
                    "icon": display.get("icon", ""),
                    "tier": int(display.get("tier", 2)),
                    "count": count,
                    "section_keys": list(display.get("keys", [])),
                })

        name_issues = self._name_issues()
        if name_issues["count"]:
            categories.append({"key": "duplicate_names",
                               "label": "Possible duplicate jobs",
                               "icon": "⇄", "tier": 1,
                               "count": name_issues["count"],
                               "section_keys": []})

        import web_health
        health = web_health.state(force=bool(force))
        if health.get("problems"):
            categories.append({"key": "system_health",
                               "label": "Data & sync problems",
                               "icon": "●", "tier": 0,
                               "count": len(health["problems"]),
                               "section_keys": []})

        categories.sort(key=lambda c: (c["tier"], -c["count"], c["label"]))
        return {
            "ok": True,
            "scanned": bool(cache.get("scanned")),
            "stale": bool(cache.get("stale")),
            "very_stale": bool(cache.get("very_stale")),
            "age_minutes": cache.get("age_minutes"),
            "scanned_at": cache.get("scanned_at", ""),
            "categories": categories,
            "total": sum(c["count"] for c in categories),
            "health_ok": bool(health.get("ok")),
        }

    def items(self, key, offset=0, limit=50):
        if key == "duplicate_names":
            result = self._name_issues()
            rows = result["items"]
            return self._slice(key, rows, offset, limit)
        if key == "system_health":
            import web_health
            rows = [{"client": p.get("title", "System problem"),
                     "subtitle": p.get("detail", ""),
                     "action": p.get("action", ""),
                     "severity": "high"}
                    for p in web_health.state().get("problems", [])]
            return self._slice(key, rows, offset, limit)

        display = next((d for d in hygiene_web._DISPLAY_SECTIONS
                        if d["key"] == key), None)
        if not display:
            return {"key": key, "items": [], "total": 0,
                    "next_offset": 0, "has_more": False}
        rows = []
        for section_key in display.get("keys", []):
            page = self._hygiene.get_section_items(section_key, 0, 200)
            for item in page.get("items", []):
                item["section_key"] = section_key
                rows.append(item)
        return self._slice(key, rows, offset, limit)

    @staticmethod
    def _slice(key, rows, offset, limit):
        try:
            offset = max(0, int(offset))
            limit = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            offset, limit = 0, 50
        page = rows[offset:offset + limit]
        return {"key": key, "items": page, "total": len(rows),
                "next_offset": offset + len(page),
                "has_more": offset + len(page) < len(rows)}

    @staticmethod
    def _name_issues():
        try:
            import ems_db
            import job_name_issues
            ignored = persistence.get("name_issue_ignored") or {}
            pairs = job_name_issues.find_split_pairs(
                ems_db.iter_jobs() or [], ignored=set(ignored))
            items = []
            for a, b in pairs:
                described = job_name_issues.describe(a, b)
                left, right = described["a"], described["b"]
                detail = "Compare before merging"
                if described.get("conflicts"):
                    detail = "Different: " + ", ".join(described["conflicts"])
                elif described.get("agrees"):
                    detail = "Matching: " + ", ".join(described["agrees"])
                items.append({"client": f'{left["display_name"]} ⇄ {right["display_name"]}',
                              "subtitle": detail,
                              "pair_key": described["pair_key"],
                              "severity": "medium"})
            return {"count": len(items), "items": items}
        except Exception as ex:
            return {"count": 0, "items": [], "error": str(ex)}
