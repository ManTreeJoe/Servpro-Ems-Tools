from unittest.mock import Mock
import employee_access
import emergency_admin
import pytest


def test_pending_preserves_identity_without_granting_access():
    client = Mock()
    client.current_user.return_value = {'id': 'pending', 'email': 'pending@example.com'}
    client.rpc.return_value = {'approval_enabled': True, 'access_state': 'pending', 'is_admin': False}
    assert employee_access.status(client)['access_state'] == 'pending'


def test_legacy_or_unavailable_schema_does_not_open_tools():
    client = Mock()
    client.current_user.return_value = {'id': 'nathan', 'email': 'nathan@servpro10100.com'}
    client.rpc.return_value = {'is_admin': True}
    assert employee_access.status(client)['access_state'] == 'unavailable'
    client.rpc.side_effect = RuntimeError('private server error')
    result = employee_access.status(client)
    assert result['access_state'] == 'unavailable'
    assert 'private server error' not in str(result)


def test_recovery_rejects_regular_employee_before_saving_session():
    client = Mock()
    client._raw.side_effect = [
        {'access_token': 'not-logged'},
        {'auth_mode': 'legacy', 'access_state': 'approved', 'is_admin': True},
        None,
    ]
    with pytest.raises(PermissionError):
        emergency_admin.authenticate('employee@example.com', 'not-logged', client)
    client._store_session.assert_not_called()
    assert client._raw.call_args.args[1] == '/auth/v1/logout'
    assert client._raw.call_args.kwargs['params'] == {'scope': 'local'}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_viewer_cannot_send_trello_mutations(monkeypatch, method):
    import trello_client
    monkeypatch.setattr(employee_access, "require_access", lambda: {"can_edit": False})
    monkeypatch.setattr(trello_client, "_creds", lambda: pytest.fail("Credentials accessed before authorization"))
    with pytest.raises(PermissionError):
        trello_client._call("/cards/example", method=method)


@pytest.mark.parametrize("mode", ["legacy", "emergency"])
def test_normal_entry_requires_microsoft_even_for_existing_admin(monkeypatch, mode):
    monkeypatch.setattr(employee_access, "_RECOVERY_MODE", False)
    client = Mock()
    client.current_user.return_value = {"id": "nathan", "email": "nathan@servpro10100.com"}
    client.rpc.return_value = {"approval_enabled": True, "access_state": "approved", "auth_mode": mode, "is_admin": True}
    result = employee_access.status(client)
    assert result["access_state"] == "microsoft_required"
    assert result["is_admin"] is False


def test_explicit_recovery_requires_server_recovery_admin(monkeypatch):
    monkeypatch.setattr(employee_access, "_RECOVERY_MODE", True)
    client = Mock()
    client.current_user.return_value = {"id": "nathan"}
    client.rpc.return_value = {"approval_enabled": True, "access_state": "approved", "auth_mode": "emergency", "is_admin": True}
    assert employee_access.status(client)["access_state"] == "approved"
    client.rpc.return_value["is_admin"] = False
    assert employee_access.status(client)["access_state"] == "microsoft_required"
