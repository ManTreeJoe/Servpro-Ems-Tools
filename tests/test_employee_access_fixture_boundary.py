"""The opt-in behavior fixture must never replace real admission by default."""
from types import SimpleNamespace
from unittest.mock import Mock
import inspect
import pytest
import employee_access
import home_web


def test_real_gate_blocks_unapproved_user_before_bound_method(monkeypatch):
    import supabase_client
    import app_error_reports
    # An accidentally global/autouse approved-access fixture must fail this test.
    assert inspect.isfunction(employee_access.require_access)
    monkeypatch.setattr(employee_access, '_ADMISSION', (0.0, None, None))
    monkeypatch.setattr(employee_access, '_RECOVERY_MODE', False)
    monkeypatch.setattr(supabase_client, 'current_user', lambda: {'id': 'pending-test'})
    rpc = Mock(return_value={'approval_enabled': True, 'access_state': 'pending',
                             'auth_mode': 'microsoft', 'is_admin': False})
    monkeypatch.setattr(supabase_client, 'rpc', rpc)
    with pytest.raises(PermissionError, match='administrator approval'):
        employee_access.require_access()
    rpc.assert_called_once_with('my_app_access')
    protected = Mock(side_effect=AssertionError('Unapproved user reached jobs'))
    monkeypatch.setattr(app_error_reports, 'instrument', lambda key, name, method: method)
    home = object.__new__(home_web.HomeApi)
    home._bind_methods('pipeline', SimpleNamespace(list_jobs=protected))
    assert home.pipeline_list_jobs() == {
        'ok': False, 'error': 'Sign in with Microsoft and wait for administrator approval.'}
    protected.assert_not_called()
