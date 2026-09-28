import pytest
import supabase_client as sb


@pytest.fixture(autouse=True)
def isolated_missing_cache():
    sb._MISSING_OPTIONAL.clear()
    yield
    sb._MISSING_OPTIONAL.clear()


def test_missing_optional_table_is_not_requested_for_every_card(monkeypatch):
    calls = []
    monkeypatch.setattr(sb, 'access_token', lambda: 'test-session')
    monkeypatch.setattr(sb, 'current_user', lambda: {'id': 'schema-budget-test'})
    monkeypatch.setattr(sb, 'creds', lambda: ('https://schema-budget.invalid', 'fixture'))
    def missing(*args, **kwargs):
        calls.append(args)
        raise sb.SupabaseError(404, '{"code":"PGRST205","message":"Could not find the table public.crm_pipeline_cards"}')
    monkeypatch.setattr(sb, '_raw', missing)
    for _ in range(5):
        with pytest.raises(sb.SupabaseError):
            sb.rest('GET', 'crm_pipeline_cards')
    assert len(calls) == 1


@pytest.mark.parametrize('status,body', [(500,'server error'), (401,'unauthorized'), (404,'not a schema error')])
def test_transport_and_permission_errors_do_not_disable_schema(monkeypatch, status, body):
    calls = []
    monkeypatch.setattr(sb, 'access_token', lambda: 'test-session')
    monkeypatch.setattr(sb, 'current_user', lambda: {'id': str(status)+body})
    monkeypatch.setattr(sb, 'creds', lambda: ('https://schema-budget.invalid', 'fixture'))
    def fail(*args, **kwargs):
        calls.append(args)
        raise sb.SupabaseError(status, body)
    monkeypatch.setattr(sb, '_raw', fail)
    for _ in range(2):
        with pytest.raises(sb.SupabaseError):
            sb.rest('GET','crm_pipeline_cards')
    assert len(calls) == 2


def test_missing_cache_expires_and_does_not_cross_users_or_workspaces(monkeypatch):
    now, user, department = [100.0], ['a'], ['IE']
    calls = []
    monkeypatch.setattr(sb.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(sb, 'access_token', lambda: 'test-session')
    monkeypatch.setattr(sb, 'current_user', lambda: {'id': user[0]})
    monkeypatch.setattr(sb.config, 'active_department', lambda: department[0])
    monkeypatch.setattr(sb, 'creds', lambda: ('https://scope.invalid', 'fixture'))
    def missing(*a, **k):
        calls.append(a)
        raise sb.SupabaseError(404, '{"code":"PGRST205"}')
    monkeypatch.setattr(sb, '_raw', missing)
    def read():
        with pytest.raises(sb.SupabaseError): sb.rest('GET','crm_job_log_entries')
    read(); read()
    assert len(calls) == 1
    user[0] = 'b'; read()
    department[0] = 'OC'; read()
    assert len(calls) == 3
    now[0] += 61
    read()
    assert len(calls) == 4
