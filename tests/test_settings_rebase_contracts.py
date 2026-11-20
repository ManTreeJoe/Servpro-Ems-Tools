"""Rebase contracts: fake providers, no shell or live workspace."""
import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import employee_access
import emergency_admin
import settings_web
import home_web

EXEMPT = {'employee_access_status', 'employee_sign_out',
          'supabase_sign_in_microsoft', 'supabase_cancel_microsoft'}


def test_every_bound_method_requires_access_except_exact_signin_methods(monkeypatch):
    import app_error_reports
    monkeypatch.setattr(app_error_reports, 'instrument', lambda key, attr, method: method)
    gate = Mock(side_effect=PermissionError('approval required'))
    monkeypatch.setattr(employee_access, 'require_access', gate)
    # Read every actual Api method without constructing providers or invoking them.
    root = Path(home_web.__file__).parent
    for key, module in {**home_web.SUB_MODULES, 'native_boards': 'native_boards_web',
                         'job_reconciliation': 'job_reconciliation_web'}.items():
        tree = ast.parse((root / (module + '.py')).read_text(encoding='utf-8-sig'))
        names = {n.name for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Api'
                 for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and not n.name.startswith('_') and n.name != 'attach'}
        # Also prove future/inherited callables and sign-in names on other tools are guarded.
        names |= EXEMPT | {'future_method'}
        spy = Mock(return_value={'ok': True})
        api = SimpleNamespace(**{name: spy for name in names})
        home = object.__new__(home_web.HomeApi)
        home._bind_methods(key, api)
        for name in names:
            spy.reset_mock(); gate.reset_mock()
            bound = getattr(home, key + '_' + name)
            result = bound()
            if key == 'settings' and name in EXEMPT:
                gate.assert_not_called(); spy.assert_called_once()
            else:
                gate.assert_called_once(); spy.assert_not_called()
                assert result == {'ok': False, 'error': 'approval required'}


@pytest.mark.parametrize('role', ['viewer', 'editor', 'admin'])
def test_admin_assigns_franchise_and_role(monkeypatch, role):
    import supabase_client
    monkeypatch.setattr(settings_web, '_is_admin', lambda: True)
    rpc = Mock(return_value={'updated': True})
    monkeypatch.setattr(supabase_client, 'rpc', rpc)
    result = settings_web.Api().employee_decide_user('fictional-user', 'approve', role, ['TEST'], 2)
    assert result['ok'] is True
    rpc.assert_called_once_with('employee_decide_user', {
        'p_user_id': 'fictional-user', 'p_action': 'approve', 'p_role': role,
        'p_departments': ['TEST'], 'p_revision': 2})


def test_emergency_flag_routes_to_recovery_without_opening_app(monkeypatch):
    recovery = Mock()
    monkeypatch.setattr(home_web, '_claim_single_instance', lambda: True)
    monkeypatch.setattr(emergency_admin, 'main', recovery)
    home_web.main(['--emergency-admin'])
    recovery.assert_called_once()
    assert callable(recovery.call_args.kwargs['on_authenticated'])


def test_emergency_admin_can_authenticate_and_be_admitted(monkeypatch):
    client = Mock()
    payload = {'access_token': 'synthetic', 'user': {'id': 'recovery-test'}}
    access = {'approval_enabled': True, 'auth_mode': 'emergency',
              'access_state': 'approved', 'is_admin': True}
    client._raw.side_effect = [payload, access]
    client._LOCK = nullcontext()
    client._cross_process_session_lock = nullcontext
    emergency_admin.authenticate('recovery@example.invalid', 'synthetic', client)
    client._store_session.assert_called_once_with(payload)
    client.current_user.return_value = payload['user']
    client.rpc.return_value = access
    monkeypatch.setattr(employee_access, '_RECOVERY_MODE', False)
    monkeypatch.setattr(employee_access, '_ADMISSION', (0, None, None))
    employee_access.enter_recovery()
    assert employee_access.status(client)['access_state'] == 'approved'
