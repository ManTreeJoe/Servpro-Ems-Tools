"""hygiene_web priority dashboard — display-section merges + the unified
priority feed. The feed merges items from the already-capped in-memory
_cache_grouped (no reload, memory-safe), scored by (tier, days, severity),
tagged with the display section, with the demoted 'open_jobs' excluded.
"""
import hygiene_web


def test_display_sections_merges_and_demote():
    by = {d["key"]: d for d in hygiene_web._DISPLAY_SECTIONS}
    # User-approved consolidations.
    assert set(by["docusketch"]["keys"]) == {"docusketch_needed", "docusketch"}
    assert set(by["docusign"]["keys"]) == {"docusign", "docusign_resends"}
    assert set(by["stalled"]["keys"]) == {"stalled", "anomalies"}
    # "All open jobs" demoted out of the feed (toggle, not a tile).
    assert by["open_jobs"].get("feed") is False
    # XA inquiries tile exists.
    assert "xa_inquiries" in by


def test_priority_feed_sorts_by_tier_then_age():
    api = hygiene_web.Api()
    api._cache_grouped = {
        "estimates": [{"client": "A", "days": 1}],     # tier 0
        "hygiene":   [{"card_name": "B", "days": 40}],  # tier 2, very old
        "open_jobs": [{"client": "Z", "days": 99}],     # demoted — excluded
    }
    f = api.get_priority_feed(None, 50)
    keys = [i["display_key"] for i in f["items"]]
    assert "open_jobs" not in keys
    # Tier-0 estimate outranks an old tier-2 hygiene row.
    assert f["items"][0]["display_key"] == "estimates"
    # Every item is tagged for the frontend.
    assert all("section" in i and "display_label" in i and "tier" in i
               for i in f["items"])
    # The internal sort key is stripped from the payload.
    assert all("_sort" not in i for i in f["items"])


def test_priority_feed_filter_by_display_key():
    api = hygiene_web.Api()
    api._cache_grouped = {
        "estimates": [{"client": "A", "days": 1}],
        "hygiene":   [{"card_name": "B", "days": 2}],
    }
    f = api.get_priority_feed(["estimates"], 50)
    assert len(f["items"]) == 1
    assert f["items"][0]["display_key"] == "estimates"


def test_priority_feed_merges_constituent_sections():
    api = hygiene_web.Api()
    api._cache_grouped = {
        "docusketch_needed": [{"client": "N", "days": 3}],
        "docusketch":        [{"client": "P", "days": 1}],
    }
    f = api.get_priority_feed(["docusketch"], 50)
    # Both backend sections roll up under the one Docusketch tile…
    assert len(f["items"]) == 2
    assert {i["display_key"] for i in f["items"]} == {"docusketch"}
    # …but each item keeps its own backend section for action routing.
    assert {i["section"] for i in f["items"]} == {"docusketch_needed", "docusketch"}


def test_priority_feed_empty_when_no_cache():
    api = hygiene_web.Api()  # _cache_grouped is {} before any get_cache
    f = api.get_priority_feed(None, 50)
    assert f["items"] == [] and f["total"] == 0
