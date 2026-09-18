import companycam_api as cc
import pytest


def test_signed_in_user_never_uses_old_pc_token(monkeypatch):
    monkeypatch.setattr(cc.config, 'load', lambda: {'companycam_api_token': 'old-office-key'})
    monkeypatch.setattr(cc, 'cloud_gateway_available', lambda: True)
    calls = []
    monkeypatch.setattr(cc, '_cloud_call', lambda path, **kwargs: calls.append((path, kwargs)) or {'id': 'new'})
    monkeypatch.setattr(cc.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Used the PC token instead of the signed-in user gateway')))
    assert cc._call('/projects', method='POST', data={'name': 'Test'}) == {'id': 'new'}
    assert calls[0][0] == '/projects'


def test_gateway_failure_does_not_fall_back_to_pc_key(monkeypatch):
    monkeypatch.setattr(cc, 'cloud_gateway_available', lambda: True)
    monkeypatch.setattr(cc, '_cloud_call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Reconnect')))
    monkeypatch.setattr(cc.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('changed identity after failure'))
    with pytest.raises(RuntimeError, match='Reconnect'):
        cc._call('/projects', method='POST')


def test_unconnected_user_stops_intake_before_trello_creation(monkeypatch):
    import supabase_client as sb
    import audit_web
    import new_loss_intake as nli
    monkeypatch.setattr(cc, 'is_configured', lambda: True)
    monkeypatch.setattr(cc, 'cloud_gateway_available', lambda: True)
    monkeypatch.setattr(sb, 'external_connection_status', lambda *a: {'status': 'expired'})
    monkeypatch.setattr(nli, 'create_new_loss', lambda *a, **k: pytest.fail('created a card without personal CC connection'))
    result = object.__new__(audit_web.Api).create_new_loss({'insured_name': 'Test'})
    assert not result['ok']
    assert 'own CompanyCam account' in result['error']
