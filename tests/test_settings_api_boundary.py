"""Settings bridge authorization, fake access/config only."""
import copy
import inspect
import pytest
import settings_web as settings

# Deliberate classification: every new public bridge method needs review.
EMPLOYEE_API = frozenset('''employee_access_status employee_sign_out
supabase_sign_in_microsoft supabase_cancel_microsoft attach schema settings_access user_connections
open_user_connection appearance_preferences my_franchise_folders save_my_franchise_folders
test_user_connection load property_managers save get_dept_browsers dept_config pick_dir pick_file
get_tech_roster lookup_job_identity authorize_trello trello_allowed_origin supabase_status
save_my_display_name supabase_send_code supabase_sign_in_password supabase_verify_code
supabase_sign_out first_run_status employee_setup_status employee_setup_action
my_trello_token_page save_my_trello_token trello_auth_status'''.split())
ADMIN_API = frozenset('''employee_admin_snapshot employee_decide_user admin_users admin_set_user_franchises admin_set_user_capabilities
admin_job_profiles admin_save_job_profile admin_set_job_profile_active admin_delete_job_profile
save_property_manager set_dept_browser add_department remove_department set_multi_dept
save_department open_data_folder open_config_file save_tech_roster open_tech_roster
backfill_job_graph authorize_trello_manual supabase_flush_queue set_db_backend
portable_folder_migration'''.split())


def test_every_public_bridge_method_is_classified_and_admin_methods_deny(monkeypatch):
    methods = {name: method for name, method in inspect.getmembers(settings.Api, inspect.isfunction)
               if not name.startswith('_')}
    assert set(methods) == EMPLOYEE_API | ADMIN_API
    assert not EMPLOYEE_API & ADMIN_API
    monkeypatch.setattr(settings, '_is_admin', lambda: False)
    monkeypatch.setattr(settings, '_admin_enforcement_active', lambda: False)
    effects = []
    def forbidden(*args, **kwargs):
        effects.append(True)
        raise AssertionError('Denied operation reached configuration')
    for name in ('load', 'load_base', 'save', 'add_department', 'remove_department'):
        monkeypatch.setattr(settings.config, name, forbidden)
    api = settings.Api()
    for name in sorted(ADMIN_API):
        args = [None for p in inspect.signature(methods[name]).parameters.values()
                if p.name != 'self' and p.default is inspect.Parameter.empty]
        result = getattr(api, name)(*args)
        assert result.get('ok') is False, name
        assert 'Administrator access' in result.get('error', ''), name
    assert not effects


SECRETS = {'supabase_anon_key', 'trello_api_key', 'trello_token', 'companycam_api_token',
           'companycam_org_key', 'graph_client_secret', 'graph_refresh_token', 'service_role_key'}

@pytest.mark.parametrize('method', ['load', 'dept_config'])
@pytest.mark.parametrize('admin', [False, True])
def test_settings_responses_filter_secrets_recursively(monkeypatch, method, admin):
    secret_values = {key: 'synthetic-sensitive-'+key for key in SECRETS}
    state = {**secret_values, 'appearance': 'dark', 'active_department': 'TEST',
             'departments': {'TEST': {**secret_values, 'label': 'Fictional office',
                 'nested': [{**secret_values, 'office_phone': 'fictional'}]}}}
    original = copy.deepcopy(state)
    monkeypatch.setattr(settings, '_is_admin', lambda: admin)
    monkeypatch.setattr(settings.config, 'load', lambda: state)
    monkeypatch.setattr(settings.config, 'load_base', lambda: state)
    monkeypatch.setattr(settings.config, 'check_department_integrity', lambda: [])
    result = getattr(settings.Api(), method)()
    def walk(value):
        if isinstance(value, dict):
            assert not SECRETS.intersection(value)
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
        elif isinstance(value, str):
            assert not value.startswith('synthetic-sensitive-')
    if not admin:
        walk(result)
        if method == 'dept_config':
            assert not SECRETS.intersection(f['key'] for f in result['fields'])
    elif method == 'load':
        assert result == original
    else:
        assert result['base']['trello_token'] == secret_values['trello_token']
        assert result['departments'][0]['overrides']['companycam_api_token'] == secret_values['companycam_api_token']
    assert state == original


def test_admin_lookup_error_is_not_admin(monkeypatch):
    import account_access
    monkeypatch.setattr(account_access, 'current_access', lambda: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(settings, '_signed_in_email', lambda: 'nathan@servpro10100.com')
    assert settings._is_admin() is False


def test_employee_signout_does_not_switch_backend(monkeypatch):
    import sys
    import types
    calls = []
    monkeypatch.setitem(sys.modules, 'supabase_client', types.SimpleNamespace(sign_out=lambda: calls.append('sign_out')))
    monkeypatch.setitem(sys.modules, 'web_health', types.SimpleNamespace(invalidate_grant_cache=lambda: None))
    monkeypatch.setattr(settings, '_is_admin', lambda: False)
    monkeypatch.setattr(settings.Api, 'set_db_backend', lambda *args: pytest.fail('Sign-out must not switch backend'))
    assert settings.Api().supabase_sign_out() == {'ok': True, 'message': 'Signed out.'}
    assert calls == ['sign_out']
