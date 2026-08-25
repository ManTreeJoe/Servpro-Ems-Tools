from __future__ import annotations

import exceptions_web


def test_summary_aggregates_existing_sources(monkeypatch):
    api = exceptions_web.Api()
    monkeypatch.setattr(api._hygiene, "get_cache", lambda: {
        "scanned": True, "stale": False, "age_minutes": 12,
        "sections": [{"key": "one", "count": 2},
                     {"key": "two", "count": 3}],
        "display": [{"key": "work", "label": "Work", "icon": "!",
                     "tier": 0, "keys": ["one", "two"]}],
    })
    monkeypatch.setattr(api, "_name_issues", lambda: {"count": 0, "items": []})
    import web_health
    monkeypatch.setattr(web_health, "state", lambda force=False: {"ok": True, "problems": []})
    result = api.summary()
    assert result["categories"][0]["count"] == 5
    assert result["total"] == 5


def test_items_delegate_to_hygiene_cache(monkeypatch):
    api = exceptions_web.Api()
    monkeypatch.setattr(exceptions_web.hygiene_web, "_DISPLAY_SECTIONS",
                        [{"key": "combined", "keys": ["a", "b"]}])
    monkeypatch.setattr(api._hygiene, "get_section_items",
                        lambda key, offset, limit: {"items": [{"client": key}]})
    result = api.items("combined")
    assert [row["client"] for row in result["items"]] == ["a", "b"]
    assert result["total"] == 2
