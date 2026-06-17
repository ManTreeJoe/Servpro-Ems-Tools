"""APA item parser — splits 'Brew, Brian - AAA-Testing/Clearance-extended'
into {text, sub, status}. Locks in:
- Status detection from end of string (longest match wins)
- Sub-category detection
- pending vs pending(User) mapping
- Estimator-name as sub for audit-section items
- Franchise tag round-trip via persistence
"""
import pytest

import apa_monitor_gui as apa
import persistence


class _FakePanel:
    """The bound method `_wrap_item` is plain logic — no widget access. We
    can call it on a stub instead of constructing the full Tk panel."""
    pass


def _wrap(text):
    # Bypass tk by calling the unbound method on a stub that has no state
    return apa.APAMonitorApp._wrap_item(_FakePanel(), text)


@pytest.fixture
def _isolate_state(tmp_path, monkeypatch):
    """Point persistence at a temp state.json so franchise-tag tests
    don't see the user's real tags."""
    monkeypatch.setattr(persistence, "_STATE_PATH",
                         str(tmp_path / "state.json"))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


def test_full_compound_string():
    item = _wrap("Brew, Brian - AAA-Testing/Clearance-extended")
    assert item["text"] == "Brew, Brian - AAA"
    assert item["sub"] == "Testing/Clearance"
    assert item["status"] == "extended"


def test_pending_upload_status():
    item = _wrap("Smith, John - State Farm-pending upload")
    assert item["status"] == "pending upload"


def test_legacy_uploading_normalizes_to_pending_upload():
    # "uploading" was replaced by "pending upload" (2026-06-17); legacy
    # entries must normalize so they pick up the universal highlight.
    item = _wrap("Smith, John - State Farm-uploading")
    assert item["status"] == "pending upload"


def test_franchise_key_strips_claim_label_to_base_insured():
    # Franchise belongs to the INSURED, not the claim — both claims of a
    # multi-claim job must resolve the same franchise tag, even though
    # their APA rows now carry the claim label.
    import apa_logic
    base = apa_logic._franchise_key("Sayra Mansolino - AAA")
    assert apa_logic._franchise_key("Sayra Mansolino 1st Claim") == base
    assert apa_logic._franchise_key(
        "Sayra Mansolino 2nd Claim (Kitchen)") == base
    assert base == "sayra mansolino"


def test_status_options_use_pending_upload_not_uploading():
    import apa_logic
    assert "pending upload" in apa_logic.STATUS_OPTIONS
    assert "uploading" not in apa_logic.STATUS_OPTIONS
    # And "pending upload" highlights (universal, like audit rejections).
    assert "pending upload" in apa_logic.HIGHLIGHT_STATUSES


def test_pending_user_collapses_to_pending():
    # 'pending(User)' / 'pending(user)' come from prior-day docs and must
    # round-trip back to plain 'pending' on parse
    item = _wrap("Smith, John - State Farm-pending(User)")
    assert item["status"] == "pending"


def test_no_status_no_sub():
    item = _wrap("Camp, John - AAA")
    assert item["text"] == "Camp, John - AAA"
    assert item["sub"] == ""
    assert item["status"] == ""


def test_addl_work_missing_items_sub():
    # Recent SUB_OPTIONS addition — must round-trip
    item = _wrap("Brew, Brian - AAA-Add'l Work/Missing Items-pending")
    assert item["sub"] == "Add'l Work/Missing Items"
    assert item["status"] == "pending"


def test_estimator_name_as_sub_in_audit():
    item = _wrap("Smith - State Farm-AARON L-pending")
    assert item["sub"] == "AARON L"
    assert item["status"] == "pending"


def test_franchise_field_initialized():
    item = _wrap("Camp, John - AAA")
    assert "franchise" in item


def test_franchise_tag_applied_on_parse(_isolate_state):
    """A persisted tag for the normalized client text should be
    re-applied when an item with the same text is parsed back from
    a saved doc. Key derivation matches _franchise_key — which strips
    the carrier suffix down to just the client surname/name."""
    persistence.set_franchise_tag(apa._franchise_key("Brew, Brian - AAA"),
                                   "South Cleveland")
    item = _wrap("Brew, Brian - AAA-Testing/Clearance-pending")
    assert item["text"] == "Brew, Brian - AAA"
    assert item["franchise"] == "South Cleveland"


def test_franchise_tag_no_match_returns_blank(_isolate_state):
    """No tag for this client text → franchise stays blank."""
    persistence.set_franchise_tag("someone, else - aaa", "South Cleveland")
    item = _wrap("Brew, Brian - AAA")
    assert item["franchise"] == ""


def test_franchise_key_normalizes_whitespace_and_case(_isolate_state):
    """Saved key normalization matches lookup normalization — extra
    spaces or different casing in the doc still hit the saved tag."""
    persistence.set_franchise_tag(apa._franchise_key("Brew, Brian - AAA"),
                                   "South Cleveland")
    item = _wrap("BREW,  Brian  - AAA-pending")
    assert item["franchise"] == "South Cleveland"


def test_franchise_set_and_clear_round_trip(_isolate_state):
    """Setting a tag, then clearing it via empty franchise removes the
    entry — a subsequent parse with the same text gets blank, not
    stale data."""
    key = apa._franchise_key("Brew, Brian - AAA")
    persistence.set_franchise_tag(key, "South Cleveland")
    assert _wrap("Brew, Brian - AAA")["franchise"] == "South Cleveland"
    # Simulate the "(none)" menu pick — _set_item_franchise calls this
    # with franchise="" which pops the entry.
    persistence.set_franchise_tag(key, "")
    assert _wrap("Brew, Brian - AAA")["franchise"] == ""
