"""Read-only status for Settings navigation; synthetic providers only."""
import sys
import types
import pytest
import settings_web

@pytest.mark.parametrize('enabled,paused,expected', [(False,False,True),(True,False,False),(True,True,True)])
def test_health_reports_effective_write_pause(monkeypatch, enabled, paused, expected):
    monkeypatch.setitem(sys.modules, 'supabase_client', types.SimpleNamespace(health=lambda: {'reachable':True,'signed_in':True}))
    monkeypatch.setitem(sys.modules, 'ems_db', types.SimpleNamespace(backend_name=lambda:'supabase'))
    monkeypatch.setitem(sys.modules, 'ems_db_offline', types.SimpleNamespace(status=lambda:{'queued':2}))
    def guard(method):
        assert method == 'POST'
        if not enabled: raise RuntimeError('writes disabled')
    monkeypatch.setitem(sys.modules, 'trello_write_guard', types.SimpleNamespace(require_write_enabled=guard))
    monkeypatch.setattr(settings_web.config, 'load', lambda:{'trello_writes_paused':paused})
    result = settings_web.Api().supabase_status()
    assert result['trello_writes_paused'] is expected
    assert result['offline']['queued'] == 2
