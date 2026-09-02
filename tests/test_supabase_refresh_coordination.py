import time

import pytest

import supabase_client


def test_refresh_reuses_session_rotated_by_another_instance(monkeypatch):
    old = {"access_token": "old-access", "refresh_token": "old-refresh", "expires_at": 0}
    new = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_at": time.time() + 3600}
    monkeypatch.setattr(supabase_client, "_read_session", lambda: new)
    monkeypatch.setattr(supabase_client.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        supabase_client, "_raw",
        lambda *a, **k: (_ for _ in ()).throw(supabase_client.SupabaseError(
            400, '{"error_code":"refresh_token_already_used"}')),
    )
    assert supabase_client._refresh(old) == new


def test_access_token_rereads_session_inside_process_lock(monkeypatch):
    fresh = {"access_token": "winner", "refresh_token": "new", "expires_at": time.time() + 3600}
    monkeypatch.setattr(supabase_client, "_read_session", lambda: fresh)
    assert supabase_client.access_token() == "winner"


def test_spent_refresh_token_without_a_winner_expires_the_local_session(monkeypatch):
    old = {"access_token": "old-access", "refresh_token": "spent",
           "expires_at": 0}
    saved = []
    monkeypatch.setattr(supabase_client, "_read_session", lambda: old)
    monkeypatch.setattr(supabase_client, "_write_session", saved.append)
    monkeypatch.setattr(supabase_client.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        supabase_client, "_raw",
        lambda *a, **k: (_ for _ in ()).throw(supabase_client.SupabaseError(
            400, '{"error_code":"refresh_token_already_used"}')),
    )

    with pytest.raises(supabase_client.NotSignedIn, match="Sign in again"):
        supabase_client._refresh(old)
    assert saved == [{}]
