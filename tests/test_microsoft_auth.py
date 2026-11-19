from contextlib import nullcontext
from urllib.parse import parse_qs, urlsplit

import pytest
import microsoft_auth as auth
import supabase_client as sb


class Server:
    code = None
    denied = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def handle_request(self):
        self.code = 'one-time-code'


@pytest.fixture
def flow(monkeypatch):
    calls, saved, urls = [], [], []
    user = {'id': 'existing-user', 'email': 'nathan@example.test',
            'email_confirmed_at': '2026-11-19T00:00:00Z',
            'identities': [{'provider': 'azure'}]}

    def raw(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == '/auth/v1/settings':
            return {'external': {'azure': True}}
        if path == '/auth/v1/token':
            return {'access_token': 'private-access', 'refresh_token': 'private-refresh', 'user': {'id': 'unchecked'}}
        if path == '/auth/v1/user':
            return user
        return None

    monkeypatch.setattr(sb, 'creds', lambda: ('https://api.example.test', 'public-key'))
    monkeypatch.setattr(sb, '_raw', raw)
    monkeypatch.setattr(sb, '_store_session', lambda payload: saved.append(payload))
    monkeypatch.setattr(sb, '_cross_process_session_lock', nullcontext)
    monkeypatch.setattr(auth, '_listener', Server)
    monkeypatch.setattr(auth.webbrowser, 'open', lambda url, **kw: urls.append(url) or True)
    return calls, saved, urls, user


def test_pkce_login_stores_verified_identity_and_no_microsoft_password(flow):
    calls, saved, urls, user = flow
    assert auth.sign_in('NATHAN@example.test') == user
    params = parse_qs(urlsplit(urls[0]).query)
    exchange = next(c[2] for c in calls if c[1] == '/auth/v1/token')
    assert params['provider'] == ['azure']
    assert params['redirect_to'] == [auth.REDIRECT]
    assert params['code_challenge'] == [auth._challenge(exchange['body']['code_verifier'])]
    assert exchange['params'] == {'grant_type': 'pkce'}
    assert saved[0]['user']['id'] == 'existing-user'
    assert 'password' not in str(saved)
    assert not any(c[1] == '/auth/v1/logout' for c in calls)


def test_wrong_microsoft_account_preserves_prior_session_and_revokes_only_new_session(flow):
    calls, saved, _, user = flow
    user['email'] = 'someone-else@example.test'
    with pytest.raises(ValueError, match='does not match'):
        auth.sign_in('nathan@example.test')
    assert not saved
    logout = next(c for c in calls if c[1] == '/auth/v1/logout')
    assert logout[2]['params'] == {'scope': 'local'}
    assert logout[2]['token'] == 'private-access'


def test_microsoft_account_picker_requires_no_typed_email(flow):
    _, saved, _, user = flow
    assert auth.sign_in() == user
    assert saved[0]['user']['email'] == 'nathan@example.test'


def test_unverified_identity_is_not_stored(flow):
    _, saved, _, user = flow
    user['email_confirmed_at'] = None
    with pytest.raises(ValueError, match='could not be verified'):
        auth.sign_in('nathan@example.test')
    assert not saved


def test_cancel_can_be_retried(flow, monkeypatch):
    _, saved, _, _ = flow

    class Cancelled(Server):
        def handle_request(self):
            auth.cancel()

    monkeypatch.setattr(auth, '_listener', Cancelled)
    with pytest.raises(ValueError, match='cancelled'):
        auth.sign_in('nathan@example.test')
    assert not saved
    monkeypatch.setattr(auth, '_listener', Server)
    assert auth.sign_in('nathan@example.test')['id'] == 'existing-user'


def test_timeout_does_not_replace_session(flow):
    _, saved, _, _ = flow
    with pytest.raises(ValueError, match='timed out'):
        auth.sign_in('nathan@example.test', timeout=0)
    assert not saved


def test_browser_failure_does_not_replace_session(flow, monkeypatch):
    _, saved, _, _ = flow
    monkeypatch.setattr(auth.webbrowser, 'open', lambda *a, **kw: False)
    with pytest.raises(ValueError, match='Could not open'):
        auth.sign_in('nathan@example.test')
    assert not saved


def test_transport_errors_conceal_tokens(flow, monkeypatch):
    _, saved, _, _ = flow
    def fail(*args, **kwargs):
        raise sb.SupabaseError(400, 'private-token-in-error')
    monkeypatch.setattr(sb, '_raw', fail)
    with pytest.raises(ValueError) as error:
        auth.sign_in('nathan@example.test')
    assert 'private-token' not in str(error.value)
    assert not saved


def test_changed_backend_is_not_used_for_exchange(flow, monkeypatch):
    calls, saved, _, _ = flow
    count = 0
    def creds():
        nonlocal count
        count += 1
        return ('https://first.example.test' if count == 1 else 'https://changed.example.test', 'public')
    monkeypatch.setattr(sb, 'creds', creds)
    with pytest.raises(ValueError, match='server changed'):
        auth.sign_in('nathan@example.test')
    assert not saved
    assert not any(c[1] == '/auth/v1/token' for c in calls)


def test_api_selects_shared_backend_after_microsoft_success(flow, monkeypatch):
    import settings_web
    actions = []
    monkeypatch.setattr(settings_web, '_use_shared_jobs_after_sign_in', lambda: actions.append('shared'))
    monkeypatch.setattr(settings_web, '_invalidate', lambda why: actions.append(why))
    result = settings_web.Api().supabase_sign_in_microsoft('nathan@example.test')
    assert result['ok']
    assert actions[0] == 'shared'


def test_rfc7636_challenge():
    assert auth._challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk') == 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'


def test_loopback_callback_rejects_wrong_host_and_duplicate_codes(monkeypatch):
    import http.client
    import threading
    monkeypatch.setattr(auth, 'PORT', 0)
    with auth._listener() as server:
        port = server.server_address[1]
        monkeypatch.setattr(auth, 'PORT', port)
        assert server.server_address[0] == '127.0.0.1'
        for path, host, status in [
            (auth.CALLBACK_PATH+'?code=forged', 'evil.example', 404),
            (auth.CALLBACK_PATH+'?code=one&code=two', f'127.0.0.1:{port}', 404),
            (auth.CALLBACK_PATH+'?code=valid', f'127.0.0.1:{port}', 200),
        ]:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                conn.request('GET', path, headers={'Host':host})
                response = conn.getresponse()
                assert response.status == status
                assert response.getheader('Cache-Control') == 'no-store'
                assert b'valid' not in response.read()
            finally:
                conn.close()
                thread.join(timeout=3)
            assert server.code == ('valid' if status == 200 else None)
