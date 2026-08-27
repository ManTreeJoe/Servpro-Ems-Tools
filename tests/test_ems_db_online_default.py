import ems_db


def test_signed_in_install_without_backend_prefers_shared_database(monkeypatch):
    import config
    import supabase_client
    monkeypatch.setattr(config, "load", lambda: {})
    monkeypatch.setattr(supabase_client, "is_configured", lambda: True)
    monkeypatch.setattr(supabase_client, "is_signed_in", lambda: True)
    assert ems_db._resolve_name() == "supabase"


def test_unsigned_install_without_backend_stays_local(monkeypatch):
    import config
    import supabase_client
    monkeypatch.setattr(config, "load", lambda: {})
    monkeypatch.setattr(supabase_client, "is_configured", lambda: True)
    monkeypatch.setattr(supabase_client, "is_signed_in", lambda: False)
    assert ems_db._resolve_name() == "sqlite"
