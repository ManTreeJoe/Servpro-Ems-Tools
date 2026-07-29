"""CompanyCam API — project name → id resolution.

The network layer is mocked; these pin the name-matching / tie-to-id logic:
comma-swapped names match, exact wins, ambiguous names defer to the user,
and an address hint breaks a same-name tie."""
import companycam_api as cc


def _projects(*rows):
    """Build raw project dicts the way the API returns them."""
    out = []
    for i, (name, addr) in enumerate(rows, 1):
        out.append({
            "id": f"proj_{i}",
            "name": name,
            "address": {"street_address_1": addr, "city": "Menifee",
                        "state": "CA", "postal_code": "92584"},
            "status": "active",
        })
    return out


def test_exact_name_ties_to_id(monkeypatch):
    monkeypatch.setattr(cc, "list_projects",
                        lambda *a, **k: _projects(("David Smith", "1 A St")))
    res = cc.find_project("David Smith")
    assert res["ok"] and res["match"]
    assert res["match"]["id"] == "proj_1"
    assert res["reason"] == "matched"


def test_comma_swapped_name_matches(monkeypatch):
    # Our client store writes "Last, First"; CompanyCam writes "First Last".
    monkeypatch.setattr(cc, "list_projects",
                        lambda *a, **k: _projects(("Foilan Bernardo", "2 B St")))
    assert cc.find_project_id("Bernardo, Foilan") == "proj_1"


def test_subset_first_name_still_matches(monkeypatch):
    monkeypatch.setattr(
        cc, "list_projects",
        lambda *a, **k: _projects(("David Smith Water Loss", "3 C St")))
    assert cc.find_project_id("David Smith") == "proj_1"


def test_ambiguous_same_name_defers(monkeypatch):
    # Two "John Miller" projects — no hint → don't guess, hand back both.
    monkeypatch.setattr(
        cc, "list_projects",
        lambda *a, **k: _projects(("John Miller", "10 Oak Ave"),
                                  ("John Miller", "55 Pine Rd")))
    res = cc.find_project("John Miller")
    assert res["match"] is None
    assert len(res["candidates"]) == 2
    assert "ambiguous" in res["reason"]


def test_address_hint_breaks_tie(monkeypatch):
    monkeypatch.setattr(
        cc, "list_projects",
        lambda *a, **k: _projects(("John Miller", "10 Oak Ave"),
                                  ("John Miller", "55 Pine Rd")))
    assert cc.find_project_id("John Miller", address_hint="55 Pine Rd") == "proj_2"


def test_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(cc, "list_projects",
                        lambda *a, **k: _projects(("Someone Else", "9 Z St")))
    res = cc.find_project("David Smith")
    assert res["ok"] and res["match"] is None


def test_blank_name_is_error(monkeypatch):
    res = cc.find_project("   ")
    assert not res["ok"]
