"""One-off audits must not split on name ORDER.

Typing "Smith John" then "John Smith" (last-first vs first-last) used to
create two separate one-off rows because canonicalization fell back to the
raw typed string. _canonicalize_client_name now matches an already-audited
one-off by token SET (order-insensitive) so the reordered name reuses it."""
import pytest

import audit_web
import persistence


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    """Redirect persistence to a tmp state.json so the test never reads the
    user's real pins (which could otherwise resolve a name)."""
    monkeypatch.setattr(persistence, "_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(persistence, "_CACHE", None)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None)
    return tmp_path


def _api(oneoffs):
    # Build the Api without running __init__ side effects; we only exercise
    # the pure name-resolution method against a seeded one-off list.
    api = audit_web.Api.__new__(audit_web.Api)
    api._oneoff_rows = oneoffs
    return api


def _isolate(api, monkeypatch):
    # Neutralize the run-doc + folder-scan candidate sources so the test is
    # deterministic regardless of the machine's live run-doc / X: share.
    monkeypatch.setattr(api, "list_folder_candidates",
                        lambda t: {"candidates": []})
    monkeypatch.setattr(audit_web, "_find_run_doc_for_date",
                        lambda d: None, raising=False)


def test_reordered_name_reuses_existing_oneoff(state_path, monkeypatch):
    api = _api([{"client": "Smith John"}])
    _isolate(api, monkeypatch)
    # Both orders resolve to the SAME existing one-off row.
    assert api._canonicalize_client_name("John Smith") == "Smith John"
    assert api._canonicalize_client_name("Smith John") == "Smith John"


def test_unrelated_name_not_falsely_reused(state_path, monkeypatch):
    api = _api([{"client": "Smith John"}])
    _isolate(api, monkeypatch)
    # No token overlap → no false reuse; falls back to the typed name.
    assert api._canonicalize_client_name("Barajas Laura") == "Barajas Laura"


def test_middle_name_variant_still_matches(state_path, monkeypatch):
    api = _api([{"client": "Mansolino, Sayra"}])
    _isolate(api, monkeypatch)
    # Same two tokens, different order + comma punctuation.
    assert api._canonicalize_client_name("Sayra Mansolino") == "Mansolino, Sayra"
